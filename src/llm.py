from __future__ import annotations

import json
from typing import Any

from src.config import LLMSettings
from src.utils.json_utils import extract_json_object


class HelloAgentRuntime:
    JSON_CORRECTION_PROMPT = (
        "你的上一条不是合法 JSON。"
        "如果要继续搜索，请只输出 TOOL_CALL；如果完成，请只输出 JSON。"
        "不要输出过程说明、解释、Markdown 或其他文本。"
    )
    JSON_ONLY_CORRECTION_PROMPT = (
        "你的上一条不是合法 JSON。现在不能调用工具，请只输出最终 JSON。"
        "不要输出过程说明、解释、Markdown 或其他文本。"
    )
    TOOL_RESULT_FOLLOWUP_PROMPT = (
        "工具执行结果：\n{tool_results}\n\n"
        "请基于这些结果继续。"
        "如果还需要搜索，请只输出 TOOL_CALL；如果信息已经足够，请只输出最终 JSON。"
        "不要输出过程说明。"
    )

    def __init__(self, settings: LLMSettings):
        self.settings = settings
        self._llm: Any | None = None
        self._simple_agent_cls: Any | None = None
        self._reflection_agent_cls: Any | None = None
        self._context_builder_cls: Any | None = None
        self._context_packet_cls: Any | None = None
        self.load_error: str = ""
        self._load_hello_agents()

    @property
    def available(self) -> bool:
        key_ok = bool(self.settings.api_key and self.settings.api_key != "your-key")
        return self.settings.enabled and key_ok and self._llm is not None

    @property
    def provider_label(self) -> str:
        if not self.available:
            return "offline-demo"
        return f"{self.settings.provider}:{self.settings.model}"

    def run_simple(
        self,
        *,
        name: str,
        system_prompt: str,
        user_prompt: str,
        tool_registry: Any | None = None,
        max_tool_iterations: int = 2,
    ) -> str:
        if not self.available or self._simple_agent_cls is None:
            return ""

        agent = self._simple_agent_cls(
            name=name,
            llm=self._llm,
            system_prompt=system_prompt,
            tool_registry=tool_registry,
            enable_tool_calling=tool_registry is not None,
        )
        return str(
            agent.run(
                user_prompt,
                max_tool_iterations=max_tool_iterations,
                temperature=self.settings.temperature,
            )
        )

    def run_json(
        self,
        *,
        name: str,
        system_prompt: str,
        user_prompt: str,
        tool_registry: Any | None = None,
        max_tool_iterations: int = 2,
    ) -> dict[str, Any] | None:
        data, _ = self.run_json_with_trace(
            name=name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tool_registry=tool_registry,
            max_tool_iterations=max_tool_iterations,
        )
        return data

    def run_json_with_trace(
        self,
        *,
        name: str,
        system_prompt: str,
        user_prompt: str,
        tool_registry: Any | None = None,
        max_tool_iterations: int = 2,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        if not self.available or self._simple_agent_cls is None:
            text = ""
            trace: dict[str, Any] = {"strict_json_loop_enabled": False}
        elif tool_registry is not None and max_tool_iterations > 0:
            text, trace = self._run_strict_json_tool_loop(
                name=name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tool_registry=tool_registry,
                max_tool_iterations=max_tool_iterations,
            )
        else:
            text, trace = self._run_json_without_tools(
                name=name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

        data = extract_json_object(text)
        preview = text.strip().replace("\r", " ").replace("\n", " ")
        trace.update(
            {
                "llm_available": self.available,
                "provider": self.provider_label,
                "raw_output_length": len(text),
                "raw_output_preview": preview[:600],
                "json_parse_ok": data is not None,
                "failure_reason": "" if data is not None else "llm_output_json_parse_failed",
            }
        )
        self._print_agent_output(name, text, data is not None)
        return data, trace

    def _print_agent_output(self, name: str, text: str, json_parse_ok: bool) -> None:
        status = "JSON_OK" if json_parse_ok else "JSON_PARSE_FAILED"
        print(f"\n========== {name} OUTPUT [{status}] ==========")
        print(text or "<empty>")
        print(f"========== END {name} OUTPUT ==========\n")

    def _run_strict_json_tool_loop(
        self,
        *,
        name: str,
        system_prompt: str,
        user_prompt: str,
        tool_registry: Any,
        max_tool_iterations: int,
    ) -> tuple[str, dict[str, Any]]:
        agent = self._simple_agent_cls(
            name=name,
            llm=self._llm,
            system_prompt=system_prompt,
            tool_registry=tool_registry,
            enable_tool_calling=True,
        )
        messages = [
            {"role": "system", "content": self._tool_loop_system_prompt(agent, system_prompt, tool_registry)},
            {"role": "user", "content": user_prompt},
        ]
        trace: dict[str, Any] = {
            "strict_json_loop_enabled": True,
            "max_tool_iterations": max_tool_iterations,
            "tool_iterations_used": 0,
            "tool_calls_executed": 0,
            "tool_call_names": [],
            "json_correction_attempts": 0,
            "non_json_no_tool_outputs": [],
            "strict_json_stop_reason": "",
        }
        current_iteration = 0
        final_response = ""

        while current_iteration < max_tool_iterations:
            response = self._invoke_tool_loop(messages, tool_registry)
            response_text = self._response_text(response)
            tool_calls = self._extract_function_tool_calls(response)

            if tool_calls:
                tool_results = []
                assistant_message = self._assistant_message_from_response(response, response_text, tool_calls)
                for call in tool_calls:
                    result = self._execute_registry_tool(agent, call["tool_name"], call["parameters"])
                    tool_results.append(result)
                    call["result"] = result
                    trace["tool_calls_executed"] += 1
                    trace["tool_call_names"].append(call["tool_name"])

                messages.append(assistant_message)
                for call in tool_calls:
                    if call.get("id"):
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call["id"],
                                "content": call["result"],
                            }
                        )
                messages.append(
                    {
                        "role": "user",
                        "content": self.TOOL_RESULT_FOLLOWUP_PROMPT.format(
                            tool_results="\n\n".join(tool_results)
                        ),
                    }
                )
                current_iteration += 1
                trace["tool_iterations_used"] = current_iteration
                continue

            if extract_json_object(response_text) is not None:
                final_response = response_text
                trace["strict_json_stop_reason"] = "valid_json"
                break

            trace["non_json_no_tool_outputs"].append(self._preview_text(response_text))
            if trace["json_correction_attempts"] < 1:
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": self.JSON_CORRECTION_PROMPT})
                trace["json_correction_attempts"] += 1
                continue

            final_response = response_text
            trace["strict_json_stop_reason"] = "non_json_after_correction"
            break

        if current_iteration >= max_tool_iterations and not final_response:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "工具调用次数已达上限。请基于已有工具结果只输出最终 JSON，"
                        "不要继续调用工具，不要输出解释。"
                    ),
                }
            )
            final_response = str(self._llm.invoke(messages, temperature=self.settings.temperature))
            trace["strict_json_stop_reason"] = "max_tool_iterations_final_answer"
            if extract_json_object(final_response) is None:
                trace["non_json_no_tool_outputs"].append(self._preview_text(final_response))
                messages.append({"role": "assistant", "content": final_response})
                messages.append({"role": "user", "content": self.JSON_ONLY_CORRECTION_PROMPT})
                final_response = str(self._llm.invoke(messages, temperature=self.settings.temperature))
                trace["json_correction_attempts"] += 1
                trace["strict_json_stop_reason"] = "max_tool_iterations_json_correction"

        return final_response, trace

    def _tool_loop_system_prompt(self, agent: Any, system_prompt: str, tool_registry: Any) -> str:
        if hasattr(agent, "_get_enhanced_system_prompt"):
            return str(agent._get_enhanced_system_prompt())
        tools_description = ""
        try:
            tools_description = tool_registry.get_tools_description()
        except Exception:
            pass
        if tools_description:
            return f"{system_prompt}\n\nAvailable tools:\n{tools_description}"
        return system_prompt

    def _invoke_tool_loop(self, messages: list[dict[str, Any]], tool_registry: Any) -> Any:
        tool_schemas = self._build_tool_schemas(tool_registry)
        if tool_schemas and hasattr(self._llm, "invoke_with_tools"):
            try:
                return self._llm.invoke_with_tools(
                    messages=messages,
                    tools=tool_schemas,
                    tool_choice="auto",
                    temperature=self.settings.temperature,
                )
            except Exception:
                pass
        return self._llm.invoke(messages, temperature=self.settings.temperature)

    def _build_tool_schemas(self, tool_registry: Any) -> list[dict[str, Any]]:
        tools = []
        try:
            tools = list(tool_registry.get_all_tools())
        except Exception:
            return []
        schemas: list[dict[str, Any]] = []
        for tool in tools:
            properties: dict[str, Any] = {}
            required: list[str] = []
            try:
                parameters = tool.get_parameters()
            except Exception:
                parameters = []
            for param in parameters:
                properties[param.name] = {
                    "type": self._json_schema_type(getattr(param, "type", "string")),
                    "description": getattr(param, "description", "") or "",
                }
                default = getattr(param, "default", None)
                if default is not None:
                    properties[param.name]["default"] = default
                if getattr(param, "required", True):
                    required.append(param.name)
            schema: dict[str, Any] = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                    },
                },
            }
            if required:
                schema["function"]["parameters"]["required"] = required
            schemas.append(schema)
        return schemas

    def _json_schema_type(self, param_type: str) -> str:
        normalized = (param_type or "").lower()
        if normalized in {"string", "number", "integer", "boolean", "array", "object"}:
            return normalized
        return "string"

    def _response_text(self, response: Any) -> str:
        if hasattr(response, "choices"):
            try:
                message = response.choices[0].message
                return str(message.content or "")
            except Exception:
                return str(response)
        if hasattr(response, "content"):
            return str(response.content or "")
        return str(response)

    def _extract_function_tool_calls(self, response: Any) -> list[dict[str, Any]]:
        if not hasattr(response, "choices"):
            return []
        try:
            raw_calls = response.choices[0].message.tool_calls or []
        except Exception:
            return []
        calls: list[dict[str, Any]] = []
        for raw_call in raw_calls:
            try:
                arguments = json.loads(raw_call.function.arguments or "{}")
            except Exception:
                arguments = {}
            calls.append(
                {
                    "id": getattr(raw_call, "id", ""),
                    "tool_name": raw_call.function.name,
                    "parameters": arguments,
                    "raw": raw_call,
                }
            )
        return calls

    def _assistant_message_from_response(
        self,
        response: Any,
        response_text: str,
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if hasattr(response, "choices"):
            try:
                message = response.choices[0].message
                return {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["tool_name"],
                                "arguments": json.dumps(call["parameters"], ensure_ascii=False),
                            },
                        }
                        for call in tool_calls
                    ],
                }
            except Exception:
                pass
        return {"role": "assistant", "content": response_text}

    def _execute_registry_tool(self, agent: Any, tool_name: str, parameters: dict[str, Any]) -> str:
        resolved_name = self._resolve_tool_name(agent.tool_registry, tool_name)
        return agent._execute_tool_call(resolved_name, parameters)

    def _resolve_tool_name(self, tool_registry: Any, tool_name: str) -> str:
        try:
            if tool_registry.get_tool(tool_name) is not None:
                return tool_name
            prefixed = f"travel_{tool_name}"
            if tool_registry.get_tool(prefixed) is not None:
                return prefixed
        except Exception:
            pass
        return tool_name

    def _run_json_without_tools(
        self,
        *,
        name: str,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, dict[str, Any]]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        trace: dict[str, Any] = {
            "strict_json_loop_enabled": False,
            "json_correction_attempts": 0,
            "non_json_no_tool_outputs": [],
            "strict_json_stop_reason": "plain_json_call",
        }
        text = str(self._llm.invoke(messages, temperature=self.settings.temperature))
        if extract_json_object(text) is not None:
            return text, trace

        trace["non_json_no_tool_outputs"].append(self._preview_text(text))
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": self.JSON_ONLY_CORRECTION_PROMPT})
        corrected = str(self._llm.invoke(messages, temperature=self.settings.temperature))
        trace["json_correction_attempts"] = 1
        trace["strict_json_stop_reason"] = "plain_json_correction"
        return corrected, trace

    def _preview_text(self, text: str) -> str:
        return text.strip().replace("\r", " ").replace("\n", " ")[:300]

    def run_reflection(
        self,
        *,
        name: str,
        task: str,
        custom_prompts: dict[str, str] | None = None,
        max_iterations: int = 2,
    ) -> str:
        if not self.available or self._reflection_agent_cls is None:
            return ""

        agent = self._reflection_agent_cls(
            name=name,
            llm=self._llm,
            max_iterations=max_iterations,
            custom_prompts=custom_prompts,
        )
        return str(agent.run(task, temperature=self.settings.temperature))

    def build_context(
        self,
        *,
        user_query: str,
        system_instructions: str,
        packets: list[tuple[str, dict[str, Any]]],
        max_tokens: int = 5000,
    ) -> str:
        if self._context_builder_cls is None or self._context_packet_cls is None:
            body = "\n\n".join(content for content, _ in packets)
            return f"{system_instructions}\n\nCurrent task: {user_query}\n\n{body}"

        from hello_agents.context import ContextConfig

        context_packets = [
            self._context_packet_cls(content=content, metadata=metadata)
            for content, metadata in packets
            if content.strip()
        ]
        builder = self._context_builder_cls(config=ContextConfig(max_tokens=max_tokens, min_relevance=0.0))
        return builder.build(
            user_query=user_query,
            system_instructions=system_instructions,
            additional_packets=context_packets,
        )

    def _load_hello_agents(self) -> None:
        try:
            from hello_agents import HelloAgentsLLM
            from hello_agents.agents.reflection_agent import ReflectionAgent
            from hello_agents.agents.simple_agent import SimpleAgent
            from hello_agents.context import ContextBuilder, ContextPacket

            self._llm = HelloAgentsLLM(
                api_key=self.settings.api_key,
                model=self.settings.model,
                base_url=self.settings.base_url,
                provider=self.settings.provider if self.settings.provider != "openai-compatible" else "auto",
                temperature=self.settings.temperature,
                timeout=int(self.settings.timeout_seconds),
            )
            self._simple_agent_cls = SimpleAgent
            self._reflection_agent_cls = ReflectionAgent
            self._context_builder_cls = ContextBuilder
            self._context_packet_cls = ContextPacket
        except Exception as exc:
            self._llm = None
            self._simple_agent_cls = None
            self._reflection_agent_cls = None
            self._context_builder_cls = None
            self._context_packet_cls = None
            self.load_error = str(exc)
