"""
Memory extraction module for filtering important information before storing in RAG memory.

This module provides functionality to extract only key moments from conversations
using LLM-based analysis, following a structured importance scoring system.
"""

import json
import re
from typing import Optional, Dict, Any, List
from loguru import logger

from .stateless_llm.stateless_llm_interface import StatelessLLMInterface
from prompts import prompt_loader


class MemoryExtractor:
    """Extracts important memories from conversation messages using LLM analysis."""

    def __init__(self, llm: StatelessLLMInterface, system_prompt: str):
        """Initialize memory extractor.

        Args:
            llm: LLM instance to use for memory extraction
            system_prompt: System prompt for memory extraction (loaded from prompt file)
        """
        self._llm = llm
        self._system_prompt = system_prompt

    async def extract_memories(
        self, role: str, content: str, conversation_context: str = ""
    ) -> Dict[str, Any]:
        """Extract important memories from a message.

        Args:
            role: Message role ("human" or "ai")
            content: Message content to analyze
            conversation_context: Optional additional context for better analysis

        Returns:
            Dictionary with structure:
            {
                "importance": float (0.0-1.0),
                "memories": [
                    {
                        "summary": str,
                        "tags": List[str],
                        "source": str
                    }
                ]
            }
            Returns default empty structure if extraction fails.
        """
        if not content or not content.strip():
            return {"importance": 0.0, "memories": []}

        try:
            # Format the input for analysis
            role_label = "User" if role == "human" else "Assistant"
            input_text = f"{role_label}: {content}"

            if conversation_context:
                input_text = f"Context: {conversation_context}\n\n{input_text}"

            # Create messages for LLM
            messages = [
                {
                    "role": "user",
                    "content": f"Analyze the following message and extract important information:\n\n{input_text}",
                }
            ]

            # Collect complete response from async iterator
            response_text = ""
            async for chunk in self._llm.chat_completion(
                messages=messages, system=self._system_prompt
            ):
                if isinstance(chunk, str):
                    response_text += chunk
                # Skip non-string chunks (like tool calls)

            if not response_text.strip():
                logger.warning("Empty response from LLM during memory extraction")
                return {"importance": 0.0, "memories": []}

            # Parse JSON from response
            extracted_data = self._parse_json_response(response_text)

            if not extracted_data:
                logger.warning(
                    f"Failed to parse memory extraction response: {response_text[:200]}"
                )
                return {"importance": 0.0, "memories": []}

            # Validate structure
            if not isinstance(extracted_data, dict):
                logger.warning("Memory extraction response is not a dictionary")
                return {"importance": 0.0, "memories": []}

            importance = extracted_data.get("importance", 0.0)
            memories = extracted_data.get("memories", [])

            # Validate memories structure
            if not isinstance(memories, list):
                logger.warning("Memories field is not a list")
                return {"importance": 0.0, "memories": []}

            # Filter out invalid memory entries
            valid_memories = []
            for memory in memories:
                if isinstance(memory, dict) and "summary" in memory:
                    valid_memories.append(memory)

            logger.debug(
                f"Extracted {len(valid_memories)} memories with importance {importance}"
            )

            return {"importance": float(importance), "memories": valid_memories}

        except Exception as e:
            logger.error(f"Error during memory extraction: {e}")
            return {"importance": 0.0, "memories": []}

    def _parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse JSON from LLM response, handling common formatting issues.

        Args:
            text: Raw text response from LLM

        Returns:
            Parsed dictionary or None if parsing fails
        """
        # Remove markdown code blocks if present
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        text = text.strip()

        # Try to find JSON object in the text
        # Look for content between first { and last }
        start_idx = text.find("{")
        end_idx = text.rfind("}")

        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
            logger.warning("No JSON object found in response")
            return None

        json_str = text[start_idx : end_idx + 1]

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error: {e}, attempting to fix...")

            # Try to fix common JSON issues
            # Remove trailing commas
            json_str = re.sub(r",\s*}", "}", json_str)
            json_str = re.sub(r",\s*]", "]", json_str)

            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON after fixes: {json_str[:200]}")
                return None


def create_memory_extractor(
    llm: StatelessLLMInterface,
) -> Optional[MemoryExtractor]:
    """Create a memory extractor instance with default system prompt.

    Args:
        llm: LLM instance to use for extraction

    Returns:
        MemoryExtractor instance or None if prompt loading fails
    """
    try:
        system_prompt = prompt_loader.load_util("memory_extraction_prompt")
        return MemoryExtractor(llm=llm, system_prompt=system_prompt)
    except Exception as e:
        logger.error(f"Failed to load memory extraction prompt: {e}")
        return None
