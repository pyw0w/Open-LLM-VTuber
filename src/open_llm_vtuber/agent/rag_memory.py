"""
RAG (Retrieval-Augmented Generation) memory manager for long-term memory storage and retrieval.

This module provides persistent memory functionality by storing conversation embeddings
in a FAISS vector store and retrieving relevant context based on semantic similarity.
"""

import os
import json
import re
import sys
from typing import Optional, List, Dict, Any
from loguru import logger

try:
    import faiss
    import numpy as np
    from sentence_transformers import SentenceTransformer
    FAISS_AVAILABLE = True
except ImportError as e:
    logger.error(
        f"RAG memory dependencies not installed: {e}. "
        "Please install sentence-transformers and faiss-cpu. "
        "Note: faiss-gpu is only available on Linux, not Windows."
    )
    faiss = None
    np = None
    SentenceTransformer = None
    FAISS_AVAILABLE = False

# Check if we're on Windows
IS_WINDOWS = sys.platform == "win32"

# Check for CUDA availability
try:
    import torch

    CUDA_AVAILABLE = torch.cuda.is_available()
except ImportError:
    CUDA_AVAILABLE = False

from ..chat_history_manager import get_history, get_history_list


def _sanitize_path_component(component: str) -> str:
    """Sanitize and validate a path component."""
    sanitized = os.path.basename(component.strip())
    # Allow alphanumeric, hyphen, underscore
    if not re.match(r"^[\w\-_]+$", sanitized):
        raise ValueError(f"Invalid characters in path component: {component}")
    return sanitized


class RAGMemoryManager:
    """Manages RAG memory storage and retrieval using FAISS vector store."""

    def __init__(
        self,
        conf_uid: str,
        embedding_model: str = "all-MiniLM-L6-v2",
        context_threshold: float = 0.3,
        max_context_length: int = 800,
        device: str = "auto",
    ):
        """Initialize RAG memory manager.

        Args:
            conf_uid: Configuration unique identifier for this character
            embedding_model: Name of the sentence-transformers model to use
            context_threshold: Minimum similarity score (0-1) for retrieval
            max_context_length: Maximum characters in retrieved context
            device: Device to use for FAISS ('auto', 'cpu', or 'cuda')
        """
        if not FAISS_AVAILABLE or SentenceTransformer is None or faiss is None or np is None:
            error_msg = (
                "RAG memory requires sentence-transformers and faiss. "
                "Please install them: uv add sentence-transformers faiss-cpu"
            )
            if not IS_WINDOWS:
                error_msg += " (or faiss-gpu for CUDA support on Linux)"
            else:
                error_msg += " (Note: faiss-gpu is only available on Linux, not Windows)"
            raise ImportError(error_msg)

        # Determine device
        if device == "auto":
            if IS_WINDOWS:
                # faiss-gpu is not available on Windows, force CPU
                self.device = "cpu"
                logger.info("Windows detected: Using CPU for FAISS operations (faiss-gpu not available on Windows)")
            elif CUDA_AVAILABLE:
                try:
                    # Check if faiss has GPU support
                    if hasattr(faiss, "StandardGpuResources"):
                        self.device = "cuda"
                        logger.info("Using CUDA for FAISS operations")
                    else:
                        self.device = "cpu"
                        logger.info("CUDA available but FAISS GPU support not found, using CPU")
                except Exception as e:
                    logger.warning(f"Failed to check CUDA support: {e}, falling back to CPU")
                    self.device = "cpu"
            else:
                self.device = "cpu"
                logger.info("Using CPU for FAISS operations")
        elif device == "cuda":
            if IS_WINDOWS:
                logger.warning(
                    "CUDA requested but faiss-gpu is not available on Windows. "
                    "Falling back to CPU. For GPU support, use Linux."
                )
                self.device = "cpu"
            elif not CUDA_AVAILABLE:
                logger.warning("CUDA requested but not available, falling back to CPU")
                self.device = "cpu"
            elif not hasattr(faiss, "StandardGpuResources"):
                logger.warning("CUDA requested but FAISS GPU support not found, falling back to CPU")
                self.device = "cpu"
            else:
                self.device = "cuda"
                logger.info("Using CUDA for FAISS operations")
        else:
            self.device = "cpu"
            logger.info("Using CPU for FAISS operations")

        self.conf_uid = _sanitize_path_component(conf_uid)
        self.embedding_model_name = embedding_model
        self.context_threshold = context_threshold
        self.max_context_length = max_context_length
        self.gpu_resource = None

        # Initialize GPU resource if using CUDA
        if self.device == "cuda":
            try:
                self.gpu_resource = faiss.StandardGpuResources()
            except Exception as e:
                logger.warning(f"Failed to initialize GPU resources: {e}, falling back to CPU")
                self.device = "cpu"

        # Initialize embedding model
        try:
            logger.info(f"Loading embedding model: {embedding_model}")
            # Use GPU for embeddings if CUDA is available and device is cuda
            device_for_embeddings = "cuda" if self.device == "cuda" and CUDA_AVAILABLE else "cpu"
            self.embedder = SentenceTransformer(embedding_model, device=device_for_embeddings)
            self.embedding_dim = self.embedder.get_sentence_embedding_dimension()
            logger.info(f"Embedding model loaded on {device_for_embeddings}")
        except Exception as e:
            logger.error(f"Failed to load embedding model {embedding_model}: {e}")
            raise

        # Setup storage directory
        self.rag_dir = os.path.join("rag_memory", self.conf_uid)
        os.makedirs(self.rag_dir, exist_ok=True)

        self.index_path = os.path.join(self.rag_dir, "index.faiss")
        self.metadata_path = os.path.join(self.rag_dir, "metadata.json")

        # Initialize FAISS index
        self.index: Optional[faiss.Index] = None
        self.metadata: List[Dict[str, Any]] = []

        # Load existing index or create new one
        self._load_or_create_index()

        # Load existing memories from chat history
        self._load_existing_memories()

    def _load_or_create_index(self) -> None:
        """Load existing FAISS index or create a new one."""
        if os.path.exists(self.index_path) and os.path.exists(self.metadata_path):
            try:
                if self.device == "cuda" and self.gpu_resource is not None:
                    # Load index to CPU first, then move to GPU
                    cpu_index = faiss.read_index(self.index_path)
                    self.index = faiss.index_cpu_to_gpu(self.gpu_resource, 0, cpu_index)
                    logger.info("Loaded FAISS index to GPU")
                else:
                    self.index = faiss.read_index(self.index_path)
                    logger.info("Loaded FAISS index to CPU")
                with open(self.metadata_path, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
                logger.info(
                    f"Loaded existing RAG index with {len(self.metadata)} memories"
                )
                return
            except Exception as e:
                logger.warning(f"Failed to load existing index: {e}. Creating new one.")
                self.metadata = []

        # Create new index
        if self.device == "cuda" and self.gpu_resource is not None:
            # Create index on CPU first, then move to GPU
            cpu_index = faiss.IndexFlatL2(self.embedding_dim)
            self.index = faiss.index_cpu_to_gpu(self.gpu_resource, 0, cpu_index)
            logger.info("Created new RAG index on GPU")
        else:
            self.index = faiss.IndexFlatL2(self.embedding_dim)
            logger.info("Created new RAG index on CPU")
        self.metadata = []

    def _save_index(self) -> None:
        """Save FAISS index and metadata to disk."""
        try:
            if self.index is not None and len(self.metadata) > 0:
                # If index is on GPU, move to CPU for saving
                if self.device == "cuda" and self.gpu_resource is not None:
                    try:
                        cpu_index = faiss.index_gpu_to_cpu(self.index)
                        faiss.write_index(cpu_index, self.index_path)
                    except Exception as e:
                        logger.warning(f"Failed to convert GPU index to CPU: {e}, trying direct save")
                        # Fallback: try to save directly (may not work for GPU indices)
                        faiss.write_index(self.index, self.index_path)
                else:
                    faiss.write_index(self.index, self.index_path)
                with open(self.metadata_path, "w", encoding="utf-8") as f:
                    json.dump(self.metadata, f, ensure_ascii=False, indent=2)
                logger.debug(f"Saved RAG index with {len(self.metadata)} memories")
        except Exception as e:
            logger.error(f"Failed to save RAG index: {e}")

    def _load_existing_memories(self) -> None:
        """Load all existing conversation histories and index them."""
        try:
            history_list = get_history_list(self.conf_uid)
            total_memories = 0

            for history_info in history_list:
                history_uid = history_info["uid"]
                messages = get_history(self.conf_uid, history_uid)

                for msg in messages:
                    if msg["role"] in ("human", "ai") and msg.get("content"):
                        content = msg["content"]
                        timestamp = msg.get("timestamp", "")
                        role = msg["role"]

                        # Check if this memory already exists
                        if self._memory_exists(content, role, timestamp):
                            continue

                        # Add to index
                        self.add_memory(
                            conf_uid=self.conf_uid,
                            role=role,
                            content=content,
                            timestamp=timestamp,
                        )
                        total_memories += 1

            if total_memories > 0:
                logger.info(f"Loaded {total_memories} existing memories from history")
                self._save_index()
        except Exception as e:
            logger.error(f"Failed to load existing memories: {e}")

    def _memory_exists(self, content: str, role: str, timestamp: str) -> bool:
        """Check if a memory with the same content, role, and timestamp already exists."""
        for meta in self.metadata:
            if (
                meta.get("content") == content
                and meta.get("role") == role
                and meta.get("timestamp") == timestamp
            ):
                return True
        return False

    def add_memory(
        self, conf_uid: str, role: str, content: str, timestamp: str = ""
    ) -> None:
        """Add a memory to the vector store.

        Args:
            conf_uid: Configuration unique identifier
            role: Message role ("human" or "ai")
            content: Message content
            timestamp: Optional timestamp string
        """
        if not content or not content.strip():
            return

        # Skip if already exists
        if self._memory_exists(content, role, timestamp):
            return

        try:
            # Generate embedding
            embedding = self.embedder.encode(content, normalize_embeddings=True)
            embedding = embedding.reshape(1, -1).astype("float32")

            # Add to FAISS index
            if self.index is None:
                self.index = faiss.IndexFlatL2(self.embedding_dim)

            self.index.add(embedding)

            # Store metadata
            self.metadata.append(
                {
                    "role": role,
                    "content": content,
                    "timestamp": timestamp,
                }
            )

            # Save periodically (every 10 memories)
            if len(self.metadata) % 10 == 0:
                self._save_index()

        except Exception as e:
            logger.error(f"Failed to add memory to RAG index: {e}")

    def search_relevant_context(
        self, query: str, threshold: Optional[float] = None, max_length: Optional[int] = None
    ) -> str:
        """Search for relevant context based on query.

        Args:
            query: Search query text
            threshold: Minimum similarity score (overrides instance default if provided)
            max_length: Maximum context length (overrides instance default if provided)

        Returns:
            Formatted context string with relevant memories
        """
        if not query or not query.strip():
            return ""

        if self.index is None or len(self.metadata) == 0:
            return ""

        threshold = threshold if threshold is not None else self.context_threshold
        max_length = max_length if max_length is not None else self.max_context_length

        try:
            # Generate query embedding
            query_embedding = self.embedder.encode(query, normalize_embeddings=True)
            query_embedding = query_embedding.reshape(1, -1).astype("float32")

            # Search for top-k similar memories
            # Use a reasonable k value (min of 10 or total memories)
            k = min(10, len(self.metadata))
            if k == 0:
                return ""

            distances, indices = self.index.search(query_embedding, k)

            # Filter by threshold and collect relevant memories
            relevant_memories = []
            total_length = 0

            for i, (distance, idx) in enumerate(zip(distances[0], indices[0])):
                if idx >= len(self.metadata):
                    continue

                # Convert L2 distance to cosine similarity
                # For normalized embeddings: similarity = 1 - (distance^2 / 2)
                similarity = 1.0 - (distance * distance / 2.0)

                if similarity >= threshold:
                    meta = self.metadata[idx]
                    content = meta.get("content", "")
                    role = meta.get("role", "unknown")
                    timestamp = meta.get("timestamp", "")

                    # Format memory entry
                    role_label = "User" if role == "human" else "Assistant"
                    memory_text = f"{role_label}: {content}"

                    # Check if adding this memory would exceed max_length
                    if total_length + len(memory_text) + 2 > max_length:
                        break

                    relevant_memories.append(memory_text)
                    total_length += len(memory_text) + 2

            if not relevant_memories:
                return ""

            # Format context
            context = "Relevant past conversation context:\n" + "\n".join(
                relevant_memories
            )

            logger.debug(
                f"Retrieved {len(relevant_memories)} relevant memories "
                f"(similarity >= {threshold})"
            )

            return context

        except Exception as e:
            logger.error(f"Failed to search RAG context: {e}")
            return ""

    def save(self) -> None:
        """Explicitly save the index and metadata to disk."""
        self._save_index()
