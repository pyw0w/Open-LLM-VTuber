from typing import Type, Literal
from loguru import logger

from .agents.agent_interface import AgentInterface
from .agents.basic_memory_agent import BasicMemoryAgent
from .stateless_llm_factory import LLMFactory as StatelessLLMFactory
from .agents.hume_ai import HumeAIAgent
from .agents.letta_agent import LettaAgent

from ..mcpp.tool_manager import ToolManager
from ..mcpp.tool_executor import ToolExecutor
from typing import Optional
from .rag_memory import RAGMemoryManager
from .memory_extractor import create_memory_extractor


class AgentFactory:
    @staticmethod
    def create_agent(
        conversation_agent_choice: str,
        agent_settings: dict,
        llm_configs: dict,
        system_prompt: str,
        live2d_model=None,
        tts_preprocessor_config=None,
        **kwargs,
    ) -> Type[AgentInterface]:
        """Create an agent based on the configuration.

        Args:
            conversation_agent_choice: The type of agent to create
            agent_settings: Settings for different types of agents
            llm_configs: Pool of LLM configurations
            system_prompt: The system prompt to use
            live2d_model: Live2D model instance for expression extraction
            tts_preprocessor_config: Configuration for TTS preprocessing
            **kwargs: Additional arguments
        """
        logger.info(f"Initializing agent: {conversation_agent_choice}")

        if conversation_agent_choice == "basic_memory_agent":
            # Get the LLM provider choice from agent settings
            basic_memory_settings: dict = agent_settings.get("basic_memory_agent", {})
            llm_provider: str = basic_memory_settings.get("llm_provider")

            if not llm_provider:
                raise ValueError("LLM provider not specified for basic memory agent")

            # Get the LLM config for this provider
            llm_config: dict = llm_configs.get(llm_provider)
            interrupt_method: Literal["system", "user"] = llm_config.pop(
                "interrupt_method", "user"
            )

            if not llm_config:
                raise ValueError(
                    f"Configuration not found for LLM provider: {llm_provider}"
                )

            # Create the stateless LLM
            llm = StatelessLLMFactory.create_llm(
                llm_provider=llm_provider, system_prompt=system_prompt, **llm_config
            )

            tool_prompts = kwargs.get("system_config", {}).get("tool_prompts", {})

            # Extract MCP components/data needed by BasicMemoryAgent from kwargs
            tool_manager: Optional[ToolManager] = kwargs.get("tool_manager")
            tool_executor: Optional[ToolExecutor] = kwargs.get("tool_executor")
            mcp_prompt_string: str = kwargs.get("mcp_prompt_string", "")
            conf_uid: Optional[str] = kwargs.get("conf_uid")

            # Initialize RAG memory manager if enabled
            rag_memory_manager: Optional[RAGMemoryManager] = None
            enable_rag_memory = basic_memory_settings.get("enable_rag_memory", False)
            use_memory_filtering = basic_memory_settings.get(
                "rag_use_memory_filtering", True
            )
            
            if enable_rag_memory and conf_uid:
                try:
                    rag_embedding_model = basic_memory_settings.get(
                        "rag_embedding_model", "all-MiniLM-L6-v2"
                    )
                    rag_context_threshold = basic_memory_settings.get(
                        "rag_context_threshold", 0.3
                    )
                    rag_max_context_length = basic_memory_settings.get(
                        "rag_max_context_length", 800
                    )
                    rag_device = basic_memory_settings.get("rag_device", "auto")

                    # Create memory extractor if filtering is enabled
                    memory_extractor = None
                    if use_memory_filtering:
                        logger.info("Creating memory extractor for RAG filtering")
                        memory_extractor = create_memory_extractor(llm)
                        if not memory_extractor:
                            logger.warning(
                                "Failed to create memory extractor. "
                                "Memory filtering will be disabled."
                            )
                            use_memory_filtering = False
                        else:
                            logger.info("Memory extractor created successfully")

                    logger.info(
                        f"Initializing RAG memory manager for conf_uid: {conf_uid} "
                        f"(filtering: {use_memory_filtering})"
                    )
                    rag_memory_manager = RAGMemoryManager(
                        conf_uid=conf_uid,
                        embedding_model=rag_embedding_model,
                        context_threshold=rag_context_threshold,
                        max_context_length=rag_max_context_length,
                        device=rag_device,
                        memory_extractor=memory_extractor,
                        use_memory_filtering=use_memory_filtering,
                    )
                    logger.info("RAG memory manager initialized successfully")
                except Exception as e:
                    logger.error(
                        f"Failed to initialize RAG memory manager: {e}. "
                        "Continuing without RAG memory."
                    )
                    rag_memory_manager = None
            elif enable_rag_memory and not conf_uid:
                logger.warning(
                    "RAG memory is enabled but conf_uid is not provided. "
                    "RAG memory will be disabled."
                )

            # Create the agent with the LLM and live2d_model
            return BasicMemoryAgent(
                llm=llm,
                system=system_prompt,
                live2d_model=live2d_model,
                tts_preprocessor_config=tts_preprocessor_config,
                faster_first_response=basic_memory_settings.get(
                    "faster_first_response", True
                ),
                segment_method=basic_memory_settings.get("segment_method", "pysbd"),
                use_mcpp=basic_memory_settings.get("use_mcpp", False),
                interrupt_method=interrupt_method,
                tool_prompts=tool_prompts,
                tool_manager=tool_manager,
                tool_executor=tool_executor,
                mcp_prompt_string=mcp_prompt_string,
                rag_memory_manager=rag_memory_manager,
                conf_uid=conf_uid,
            )

        elif conversation_agent_choice == "mem0_agent":
            from .agents.mem0_llm import LLM as Mem0LLM

            mem0_settings = agent_settings.get("mem0_agent", {})
            if not mem0_settings:
                raise ValueError("Mem0 agent settings not found")

            # Validate required settings
            required_fields = ["base_url", "model", "mem0_config"]
            for field in required_fields:
                if field not in mem0_settings:
                    raise ValueError(
                        f"Missing required field '{field}' in mem0_agent settings"
                    )

            return Mem0LLM(
                user_id=kwargs.get("user_id", "default"),
                system=system_prompt,
                live2d_model=live2d_model,
                **mem0_settings,
            )

        elif conversation_agent_choice == "hume_ai_agent":
            settings = agent_settings.get("hume_ai_agent", {})
            return HumeAIAgent(
                api_key=settings.get("api_key"),
                host=settings.get("host", "api.hume.ai"),
                config_id=settings.get("config_id"),
                idle_timeout=settings.get("idle_timeout", 15),
            )

        elif conversation_agent_choice == "letta_agent":
            settings = agent_settings.get("letta_agent", {})
            return LettaAgent(
                live2d_model=live2d_model,
                id=settings.get("id"),
                tts_preprocessor_config=tts_preprocessor_config,
                faster_first_response=settings.get("faster_first_response"),
                segment_method=settings.get("segment_method"),
                host=settings.get("host"),
                port=settings.get("port"),
            )

        else:
            raise ValueError(f"Unsupported agent type: {conversation_agent_choice}")
