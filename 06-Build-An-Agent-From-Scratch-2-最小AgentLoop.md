# 06 — Build An Agent From Scratch [2]：最小 Agent Loop

> 本文是 selfstudy-ai 自学笔记的第 6 篇。
> 目标：看懂一个“最小但能跑起来”的 Agent 是由哪几块拼出来的：Agent Loop、LLM Client、Tool System，以及它们之间怎样通过消息历史互相配合。
> 原文：[Build An Agent From Scratch [2]：最小 Agent Loop](https://www.tritium.work/2026/06/08/Build%20An%20Agent%20From%20Scratch%20%5B2%5D%EF%BC%9A%E6%9C%80%E5%B0%8F%20Agent%20Loop/)
> 这是「从零搭建 Agent」系列的第二篇。上一篇先搭了理论骨架：Agent Loop 是心脏，Harness 是围绕这个循环做上下文工程和注意力管理的系统。从这一篇开始，我们把理论实践到代码里：先不做复杂的 Harness，只实现一个最小但能跑起来的 Agent Loop。

## 阅读地图：先认识这一课的关键词

这一课会出现一些工程术语。先建立一张“词卡”，后面读到它们时就不会慌：

| 术语 | 一句话解释 |
|---|---|
| Agent Loop | 让 Agent 不断“看结果、想下一步、执行动作”的循环 |
| 模型 / LLM Client | 负责调用大模型的那一层代码，相当于“给模型打电话的接线员” |
| API | 一个程序请求另一个程序提供服务的规定入口 |
| 工具调用 / Tool Call | 模型不直接执行代码，而是“点名”某个工具，由宿主程序真正执行 |
| 观察 / Observation | 工具执行后返回的结果，它会重新进入模型的眼睛 |
| 消息历史 / History | 本轮任务里已经发生的全部对话和工具结果，是模型当前“能看到的记忆” |
| 上下文 / Context | 模型这一次能看到的全部输入，包括指令、历史、工具结果 |
| 上下文窗口 | 模型一次最多能容纳多少内容的“工作台” |
| 流式输出 / Streaming | 模型一个字一个字往外吐，而不是憋到整段写完才给你 |
| Schema | 工具输入参数的“填写表单说明”，告诉模型该交什么格式的数据 |
| 事件流 / Event Stream | Agent 运行时持续发出的进度通知，UI 和日志都可以订阅 |
| Prompt Cache | 如果模型每次看到的开头内容完全一样，服务商可以复用之前算过的部分，从而省钱 |

> 通俗解释：这一课你不需要学会写代码。重点只抓四个动作：**模型说想用工具 → 程序执行工具 → 结果写回历史 → 模型再看一眼继续回答**。

---

## 这一节要实现什么？

第一篇里我们说，一个最小 Agent Loop 可以抽象成：

**感知（Observe）→ 思考（Think）→ 行动（Act）**

这句话听起来很像概念，但写成代码其实就是一个循环：

- 把用户输入和历史消息交给模型。
- 模型要么直接回答，要么请求调用工具。
- 如果模型请求工具，Agent 执行工具，把结果写回历史。
- 模型在下一轮看到工具结果，再继续回答或继续调用工具。
- 如果模型不再调用工具且目标已完成，循环结束。

这一节的目标是做一个最小的 Agent Loop，它只需要具备三个核心能力：

| 模块 | 作用 | 这一版做到什么程度 |
|---|---|---|
| Agent Loop | 驱动模型和工具之间的循环 | 支持多轮工具调用、最终回答、最大轮次保护 |
| LLM Client | 封装模型 API | 支持 OpenAI Responses API、非流式与流式接口 |
| Tool System | 让模型操作外部世界 | 支持工具注册、schema 暴露、参数校验、错误回填 |

这三个模块跑通之后，Agent 就不再只是一个“问答包装器”。它可以根据任务主动决定是否调用工具，并基于工具返回结果继续推理。

比如用户问：

```text
Calculate (123 + 456) * 789, then tell me the result.
```

普通 LLM Client 会把问题丢给模型，然后等模型直接生成答案。Agent Loop 则多了一个动作空间：

```text
User question
  -> model decides to call calculator
  -> agent executes calculator
  -> observation: 456831
  -> model sees observation
  -> final answer
```

这个“工具结果重新进入模型上下文”的动作，就是 Agent 与普通聊天机器人最关键的分界线。

> 通俗解释：普通聊天机器人像一个只能“动嘴”的人；Agent 像一个“既能动嘴、又能动手”的人。它说“我要用计算器”，宿主程序（真正负责运行工具、处理结果，并协调模型继续工作的主程序）真的去按计算器，再把屏幕上显示的答案念给它听，它再继续思考。

### 这一课最常用的概念，先拆开讲

#### 1. Responses API、Chat Completions API、Anthropic API 有什么区别？

它们都是“让程序跟大模型对话”的接口，但说话的地址、格式、能力不一样。

| API | 谁家的 | 大致定位 | 最明显的特征 |
|---|---|---|---|
| Responses API | OpenAI | 比较新的 Agent 专用接口 | 支持状态、工具调用、多模态、推理等，接口设计更面向“智能体” |
| Chat Completions API | OpenAI | 比较早的聊天接口 | 核心是“你给我一段对话历史，我还你一个回答”，状态要程序自己维护 |
| Anthropic API（Messages API） | Anthropic（Claude） | Claude 的原生聊天接口 | 字段和 OpenAI 不同，例如用 `system`、`user`、`assistant` 消息，有自己的一套工具和流式格式 |

Chat Completions 是“一轮聊天的请求”：你把完整的 `messages` 数组传过去，模型返回一个 `choices` 里的 message，多轮对话状态完全由你自己维护；

Anthropic 的 Messages API 思路与之相近，也是传 `system`/`user`/`assistant` 消息、用 content blocks 表达文本和工具调用，但协议格式、端点、流式事件都自成一派。

Responses API 则把“状态”和“行动”内建进来：它返回带 id 的 typed items（reasoning、message、function_call 等），可以用 `store: true` 或 `previous_response_id` 保持跨轮推理状态，还自带 web search、file search、code interpreter、computer use、远程 MCP 等工具，在一个请求内完成多步智能体循环。

> 通俗解释：它们都是“给模型打电话”的方式，但一个是新式总机，一个是老式总机，另一家是别家公司的总机。说的内容一样，填的表单和接线的地址不一样。Agent 想换哪一家，就得让 `LlmClient` 这个“翻译”去适应那家的格式。

#### 2. 非流式接口和流式接口有什么区别？

- **非流式接口**：程序把问题发给模型后，什么都不做，一直等到模型把整段答案生成完，再一次性拿回来。过程像“你去复印店打印一整本书，等它全部印好再交给你”。
- **流式接口**：模型开始生成后，每生成一小段就立刻发回来。过程像“打字机一个字一个字往外敲，你一边看一边等”，不用等到全部完成。

对 Agent 来说，两者最终得到的答案内容通常相同。区别主要在体验和速度：

| 比较点 | 非流式 | 流式 |
|---|---|---|
| 什么时候开始收到内容 | 全部生成完才收到 | 边生成边收到 |
| 首字等待时间 | 长 | 短 |
| 适合场景 | 后台批量处理、结果不着急展示 | 聊天框逐字显示、Agent 进度展示 |
| 对 Agent Loop 的影响 | 最终拿一个完整 `AssistantMessage` | 拿一堆 `delta` 增量，再拼成完整 `AssistantMessage` |

#### 3. 宿主程序是 Agent 接入的 LLM 吗？

不是。**宿主程序不等于 LLM。**

LLM 只是 Agent 的“大脑”，它负责理解语言、做推理、决定下一步说什么或调用什么。宿主程序是“身体 + 管家 + 工坊”：它运行 Agent Loop，真正调用 LLM，真正执行工具，管理历史消息，把结果送回给模型。

> 通俗解释：模型是顾问，只在办公室里动脑；宿主程序是执行团队，负责打电话问顾问、出门办事、把办事结果拿回来再问顾问。两者必须配合，但不能划等号。

#### 4. turn loop 是什么？

`turn` 是“一轮”，`loop` 是“循环”，合起来就是“一轮一轮地循环”。

在 Agent 里，一次完整交互可以拆成很多轮：

```text
第 1 轮：模型看完用户问题，决定调用计算器
第 2 轮：模型看到计算结果，决定调用天气工具
第 3 轮：模型看到天气结果，决定给出最终回答
结束
```

如果模型在第 1 轮就直接回答，那整个 turn loop 只有 1 轮；如果它连续调用 5 次工具，就有 6 轮（最后一次是最终回答）。

#### 5. TypeScript 是什么？

TypeScript 是一种编程语言，它是 JavaScript 的“升级版”：在 JavaScript 的基础上，增加了**类型说明**。

类型说明的作用是提前告诉程序“这里应该放文字、那里应该放数字、这个变量代表一种什么形状的对象”。这样写代码时更容易发现错误，也更容易多人协作。

> 通俗解释：JavaScript 像“普通便签”，什么都能往上写；TypeScript 像“带格子、带标签的表格”，每一格该填什么都写清楚。本文里那些 `LlmClient`、`AgentTool` 之类的形状，就是用 TypeScript 写的“表格规范”。

#### 6. hooks 里的“外部程序”指什么？

这里的“外部程序”不是模型，也不是工具，而是** Agent 主程序之外、想观察或控制 Agent 的其他程序**。

例如：一个网页界面、一个命令行工具、一个日志系统、一个监控面板。它们不想改写 Agent 内部的循环，只想知道“现在进行到哪一步了”，或者在某些时刻插入自己的逻辑。hooks 就是给这些外部程序预留的“挂钩点”。

> 通俗解释：Agent 像一台自动售货机，hooks 是它身上的外接插口。售货机不用拆开重装，外部设备插上插口就能读到“正在出货”“出货完成”这类状态。

---

## 1. Agent loop：同类 Agent 是怎么做的？

在写我们自己的实现前，作者看了两个已经存在的 Agent 源码：Codex 和 Pi。它们代表了两个很好的参照系：

- **Codex**：生产级实现，turn loop、工具 runtime、上下文压缩、hooks、权限、安全和事件系统都很完整。
- **Pi**：轻量级 TypeScript 实现，Agent Loop 非常显式，结构更简单。

> 通俗解释：“生产级”意思是已经能放到真实产品里长期稳定运行；“runtime”可以理解成工具运行时的环境；“hooks”是给外部程序预留的“挂钩点”，允许在特定时刻插入自己的逻辑。

### Codex：生产级 turn loop

Codex 的 Agent Loop 分散在 turn、sampling request、Responses stream 和 tool runtime 之间。源码注释描述了这个 turn loop：

> 在每一次 sampling request 中，模型要么返回 function call，要么返回 assistant message。
> 如果返回 function call，就执行工具，并把工具输出送回下一次 sampling request。
> 如果只返回 assistant message，就记录历史并认为 turn 完成。

抽象成伪代码大概是：

```text
while (true) {
  const prompt = buildPrompt(history, visibleTools);
  const output = await model.stream(prompt);

  if (output.hasToolCall) {
    history.push(output.toolCall);
    const result = await toolRuntime.execute(output.toolCall);
    history.push(result);
    continue;
  }

  history.push(output.assistantMessage);
  return output.assistantMessage;
}
```

> 通俗解释：这段伪代码就是“一直循环，直到模型直接回答”的翻译。`history.push` 的意思是“把这条记录追加到历史里”；`continue` 的意思是“这一轮结束，进入下一轮”。`toolRuntime.execute` 则是让宿主程序去真正运行工具。

这里再对应一下“turn loop”：伪代码里的 `while (true)` 是整个 turn loop；每次循环迭代，就是一次 `sampling request`，也就是“让模型想一次”。模型如果只回了普通消息，循环就结束；如果要求调用工具，宿主执行完工具后写回历史，再进入下一次循环。

在 Codex 的实现中，可以看到三个值得学习的点：

**第一，工具结果必须回填给模型。** 工具调用和调用结果是 conversation history 的一部分。模型下一轮必须看到 observation，才能继续推理。

**第二，工具错误也是上下文。** 在 `codex-rs/core/src/tools/parallel.rs` 里，非 fatal 的工具错误会被转换成失败的 function call output，而不是直接让整个 turn 崩掉。也就是说， `command failed`、`tool not found`、`permission denied` 这类信息都应该成为模型可见的 observation。

**第三，并行执行和顺序回填要分开。** Codex 的工具 runtime 会根据工具是否支持 parallel 选择并行或串行，但输出仍然以稳定方式写回历史，避免模型看到的上下文顺序漂移。

> 通俗解释：`fatal` 是“这个任务已经救不回来”的错误；`non-fatal` 是“这次没做成，但还可以继续尝试”的错误。好的 Agent 会把后者当成一个普通观察结果送给模型，让模型有机会自我修正，而不是直接崩溃。

### Pi：显式 Agent Loop

Pi 的核心循环在 `packages/agent/src/agent-loop.ts`，它的实现形态更适合学习。Pi 的 `runLoop` 大致是：

```text
context messages
  -> streamAssistantResponse
  -> assistant message
  -> extract tool calls
  -> execute tools
  -> append toolResult messages
  -> next turn
```

它做了两个很实用的设计：

**第一，工具执行策略可配置。** Pi 会检查全局 `toolExecution` 和每个工具自己的 `executionMode`。如果任一工具要求顺序执行，就走 sequential；否则可以 parallel。

怎么理解？全局tool execution指的是整个任务层面所有工具的执行，检查这个任务里面所有工具默认自己是怎么执行的。而“每个工具自己的execution mode”指的就是后面提到的sequential和parallel。sequential的意思是“顺序的”，parallel的意思是“平行的，并行的“。区别如下：

| 模式 | 执行方式 | 类似场景 |
|---|---|---|
| sequential | 一个一个执行，前一个结束才轮到后一个 | 排队做核酸，一个人没做完下一个人不能开始 |
| parallel | 多个工具同时开始执行 | 同时让三个人分头去买菜，买完再汇总 |

- 每个工具自己的 `executionMode` 是“这个工具个人的偏好”，可以覆盖全局默认值。
- 如果全局是 `parallel`，但某一次要调用的工具里有一个声明自己是 `sequential`，那么这一批工具就降级成顺序执行，不能并行。

**之所以“任一工具要求顺序就整体顺序”，是因为并行可能会造成依赖问题：如果工具 B 需要工具 A 的结果，而 B 提前跑，就会拿到不完整的信息。最安全的做法是：只要有一个工具说“我不能并行”，整批就乖乖排队。**

**第二，事件流是一等接口。** Pi 会发出 `agent_start`、`turn_start`、`message_start`、`tool_execution_start`、`tool_execution_end`、`agent_end` 这类事件。这样 CLI、TUI、Web UI、日志系统都可以订阅同一条 agent event stream。

> 通俗解释：事件流就像广播电台。Agent 每做一步都会广播“我开始干活了”“我在调用工具了”“工具完成了”；任何界面都可以听这个广播，不需要改 Agent 本身的逻辑。

所以我们这一版的实现策略很明确：

- **学 Codex 的调用逻辑：工具结果回填、工具错误回填、并行执行但顺序写回。**
- **学 Pi 的形态：显式 TypeScript loop、清晰的 LLM 边界、事件驱动。**

这里要明晰几个名词，“显式 TypeScript loop”：

“显式”的意思是：循环结构在代码里清清楚楚，你能直接看到 `while` 或 `for` 在反复执行“问模型、看工具调用、执行工具、写回历史”。它不靠隐藏魔法，不把循环藏在别的地方。

“TypeScript loop”就是指这个循环是用 TypeScript 写的，并且借用了 TypeScript 的类型系统，把模型、工具、消息都定义成有清晰形状的对象。

“LLM 边界清晰”：

边界是指“Agent 自己的逻辑”和“模型供应商的细节”之间有一道清楚的分界线。Agent Loop 只使用统一的 `complete()` 非流式输出/ `stream()` 流式输出和统一的 `AssistantMessage`，不直接处理 OpenAI 的字段、Anthropic 的字段、流式事件的细节。所有供应商特有的翻译都收在 `LlmClient` 里。

这里我们可以理解为两种厨子，complete的就是一锅出，一次性把菜全给你；stream则是先给你炒一个菜，然后再给你炒下一个菜。而这两个厨子其实都是agent loop的出餐方式。至于他们做什么，都是接收统一的“assistant message”。这个assistant message是由LLmClient把不同供应商的字段和细节都翻译好的。防止厨子（agent loop）听不懂。

## Agent Loop 核心代码

当前最小循环在 `src/agent/agent-loop.ts` 的 `runInternal` 里。这段agent loop代码展示了如何串联将agent loop，LLm Client tool system三部分串联起来：

```typescript
private async runInternal(
  input: string,
  options: AgentRunOptions = {}
): Promise<AgentRunResult> {
  const maxTurns = options.maxTurns ?? this.maxTurns;
  const userMessage: AgentMessage = { role: "user", content: input };
  this.messages.push(userMessage);

  let lastAssistant: AssistantMessage | undefined;

  for (let turn = 1; turn <= maxTurns; turn += 1) {
    const assistant = await this.completeAssistant(turn, {
      model: this.model,
      systemPrompt: this.systemPrompt,
      messages: [...this.messages],
      tools: this.tools.toLlmToolSpecs(),
      reasoning: options.reasoning ?? this.reasoning,
      signal: options.signal
    });

    lastAssistant = assistant;
    this.messages.push(assistant);

    const toolCalls = assistant.toolCalls ?? [];
    if (toolCalls.length === 0) {
      return this.buildResult(assistant.content, turn, "final");
    }

    const toolResults = await this.executeToolCalls(turn, toolCalls, options.signal);
    this.messages.push(...toolResults);
  }

  return this.buildResult(lastAssistant?.content ?? "", maxTurns, "max_turns");
}
```

---

拆解代码：

`runInternal` 是 Agent 循环的总入口：它先接收用户的 `input` 和本次运行的 `options`，用 `options.maxTurns ?? this.maxTurns` 确定最多能循环多少轮（如果本次设置了maxturns，也就是option.maxTurns，那就用，没有就用右边agent默认的this.maxTurns），然后把用户输入包成一条 `role: "user"` （一个给消息贴的角色标签，表示“这条消息是用户说的“，区别于模型说的 `assistant` 和工具返回的 `tool`）的 `userMessage`，通过 `this.messages.push(userMessage)` 写进当前任务的历史；<br>接着声明一个可能暂时为空的变量（`lastAssistant`），用来记住最近一次模型回答，因为程序可能在模型还没给出最终答案时被迫结束，所以要留一个位置保存最后拿到的内容。然后进入 `for (let turn = 1; turn <= maxTurns; turn += 1)` 这个循环（`turn` 是当前第几轮；从 1 开始，每跑完一轮加 1，直到超过 `maxTurns`）。<br>每一轮里，程序调用 `completeAssistant` （内部方法，负责“让模型完整地想一次并返回回答”，相当于循环里的一次 Think。）让模型思考一次，同时把 `systemPrompt`、当前完整历史（ `[...this.messages]`）、转换好的工具说明书 `this.tools.toLlmToolSpecs()`（工具说明书是把工具列表转换成模型能看懂的格式）推理强度 `reasoning` 和取消信号 `signal` 一起交给模型。<br>模型反馈后，程序把这次回答记入 `lastAssistant`，也通过 `this.messages.push(assistant)` 追加到历史里。接着读取 `assistant.toolCalls`，如果这次模型没有要求调用工具，也就是 `toolCalls.length === 0`，就说明模型已经给出最终答案，直接调用 `this.buildResult(assistant.content, turn, "final")` 返回结果并结束；如果模型确实要求调用工具，就调用 `executeToolCalls` 真正执行这些工具，再通过 `this.messages.push(...toolResults)` 把工具结果一条一条写回历史，然后进入下一轮循环，让模型看到刚刚的 observation 后继续推理。如果循环已经达到 `maxTurns` 但模型始终没有给出最终回答，程序就会走出循环，用 `lastAssistant?.content ?? ""` 兜底取出最后一次回答内容，并以 `"max_turns"` 状态调用 `buildResult` 强制结束。所以这段代码的本质就是：让模型想一次，如果它要工具就执行并把结果写回历史，再让它想一次，直到它给出最终答案或轮数用完。

Agent Loop LLM Client Tool System三部分在代码中的体现如下：

**Agent Loop**：就是这段代码本身。`for` 循环、`completeAssistant`、`executeToolCalls`、把结果 `push` 回历史，这些都是在执行“感知 → 思考 → 行动”的循环。

**LLM Client**：通过 `completeAssistant` 参与。它真正负责调用 `LlmClient.complete()` 或 `LlmClient.stream()`，也就是把 `systemPrompt`、历史、工具列表翻译成模型 API 能认得的格式。这段代码没有直接写 OpenAI 字段，只是把请求交给了 LLM Client。

**Tool System**：通过 `this.tools.toLlmToolSpecs()` 和 `executeToolCalls` 参与。前者把工具注册表里的工具转成模型能看懂的说明书，后者再根据模型发出的 `toolCalls` 去真正执行工具，并把结果写回历史

这段代码也就是 Observe / Think / Act（aka reAct）的工程版本：

| 理论概念 | 代码对应 |
|---|---|
| Observe | `messages` 里已有的 user、assistant、tool result |
| Think | `completeAssistant(...)` 调用模型 |
| Act | `executeToolCalls(...)` 执行模型请求的工具 |
| Observe again | `this.messages.push(...toolResults)` 将工具结果写回历史 |
| Stop | assistant 没有 tool call，或达到 maxTurns |

### Agent loop保持最小规模

当前项目的整体逻辑是：

```text
User input
  -> Agent.run()
  -> append user message
  -> LlmClient.complete() or StreamingLlmClient.stream()
  -> assistant message
  -> if no tool calls: return final output
  -> if tool calls:
       ToolExecutor.execute(...)
       append tool result messages
       continue next turn
```

Agent Loop不关心 OpenAI Responses API 的具体 payload，也不关心工具函数内部怎么执行。它只负责整体循环。

模型调用被归给 `LlmClient`：

```typescript
export interface LlmClient {
  complete(request: LlmRequest): Promise<AssistantMessage>;
}

export interface StreamingLlmClient extends LlmClient {
  stream(request: LlmRequest): AsyncIterable<LlmStreamEvent>;
}
```

`LlmClient` 是一个“模型调用层的合同”，它规定：任何一个能跟模型对话的客户端，都必须提供一个 `complete(request: LlmRequest)` 方法，这个方法接收一份统一格式的请求 `LlmRequest`，并返回一个 `Promise<AssistantMessage>`，意思就是“我现在先承诺，等模型生成完后会交给你一条标准化的 `AssistantMessage`”。这样 Agent Loop 就不用关心背后是 OpenAI、Anthropic 还是别的供应商，它只需要知道“我调用 `complete`，以后一定会拿到一个标准答案”。接着，`StreamingLlmClient extends LlmClient` 表示它是 `LlmClient` 的流式增强版：它自动继承了 `complete`，所以它既能用非流式方式拿完整答案，又额外增加了一个 `stream(request: LlmRequest): AsyncIterable<LlmStreamEvent>` 方法。这个方法的含义是：它也接收同样的 `LlmRequest`，但返回的不是“一次性结果”，而是一个 `AsyncIterable`，也就是一个可以一条一条读取的事件流；模型每生成一小段，就吐出一个 `LlmStreamEvent`，比如 `text_delta`、`thinking_delta`、`tool_call_delta`、`done`。<br>所以这段代码不是在写具体逻辑，而是在画一条清晰的边界：Agent Loop 只依赖 `complete()` 和 `stream()` 这两个统一入口，模型供应商的所有特殊格式都被关在具体的客户端实现里。

工具调用被压到 `ToolRegistry` 和 `ToolExecutor`：

```typescript
export type AgentTool = {
  name: string;
  description: string;
  parameters: JsonSchema;
  executionMode?: "sequential" | "parallel";
  execute(args: unknown, context: ToolExecutionContext): Promise<ToolResult> | ToolResult;
};
```

`AgentTool` 是一个“工具的标准形状”，它规定：凡是 Agent 能调用的工具，都必须具备这几样东西。`name` 是工具的名字，用来让模型点名，也用来在注册表里查找；`description` 是给模型看的工具说明，相当于“招聘启事”，告诉模型这个工具能干什么；`parameters: JsonSchema` 是工具参数的填写规则，用 `JsonSchema` 这种标准格式描述“模型应该交哪些参数、哪些必填、每个参数是什么格式”，模型看了才知道怎么正确请求这个工具。`executionMode?: "sequential" | "parallel"` 是可选字段，表示这个工具到底允许“排队一个一个执行”还是“可以和其他工具同时并行执行”；`?` 的意思是它可以不填，不填时工具就听任务级的默认策略。最后 `execute(args: unknown, context: ToolExecutionContext): Promise<ToolResult> | ToolResult` 是这个工具真正干活的方法：它接收模型提交的参数 `args` 和这次执行需要的上下文 `context`，然后返回一个 `ToolResult`；返回 `Promise<ToolResult> | ToolResult` 的意思是“这个工具可以立刻给出结果，也可以异步执行、等一会儿再给结果”，这样既支持简单的同步计算，也支持查天气、读文件这类需要等待的外部操作。所以这段代码本身没有写“计算器怎么计算”，它只是画出一个统一模板：所有工具都必须有名字、说明、参数规则、执行方式，以及一个能真正跑起来并返回结果的方法。

于是 Agent Loop 本身可以保持很小。

> **通俗解释：这里最关键的不是语法，而是“边界”。`LlmClient` 只负责和模型说话；`ToolRegistry` 只负责管理有哪些工具；`ToolExecutor` 只负责执行工具。Agent Loop 本身不亲自做这些事，它只负责喊“开始”“下一轮”“结束”。这样以后换模型、换工具，都不用重写整辆车。**

---

## 2. LLM Client：隔离模型供应商

我们的 OpenAI 格式接口接入在 `src/llm/openai-responses-client.ts`。它做两件事：

- 把内部消息结构转换成 Responses API 的 `input`。
- 把 Responses API 的输出转换回内部 `AssistantMessage`。

内部消息到 Responses input 的转换逻辑大概是：

```typescript
if (message.role === "user") {
  input.push({
    type: "message",
    role: "user",
    content: [{ type: "input_text", text: message.content }]
  });
}

if (message.role === "assistant") {
  input.push({
    type: "message",
    role: "assistant",
    content: [{ type: "output_text", text: message.content }]
  });

  for (const toolCall of message.toolCalls ?? []) {
    input.push({
      type: "function_call",
      call_id: toolCall.id,
      name: toolCall.name,
      arguments: JSON.stringify(toolCall.arguments ?? {})
    });
  }
}

if (message.role === "tool") {
  input.push({
    type: "function_call_output",
    call_id: message.toolCallId,
    output: message.content
  });
}
```

这段代码是 `OpenAIResponsesClient` 里的“翻译层”核心：它把 Agent 内部认识的 `message`，逐条翻译成 OpenAI Responses API 认识的 `input` 数组，这样 Agent Loop 不需要接触 OpenAI 的格式。

第一个分支处理 `message.role === "user"`。如果这是一条用户消息，就向 `input` 里加入一个 `type: "message"`、`role: "user"` 的对象，并把用户正文放进 `content` 数组里的 `input_text` 中。也就是说，“用户说了一句话”被翻译成了 API 认得的“一条用户输入”。

第二个分支处理 `message.role === "assistant"`。如果这是一条模型消息，就先翻译成 `type: "message"`、`role: "assistant"` 的对象，模型正文放进 `output_text`。但如果这条模型消息里还带有工具调用请求，就需要再处理 `for (const toolCall of message.toolCalls ?? [])`：`?? []` 表示没有工具调用时就当作空数组，循环不会执行。每有一个 `toolCall`，就往 `input` 里再追加一个 `type: "function_call"` 对象，其中 `call_id` 是这个工具调用在本次对话里的唯一编号，`name` 是工具名，`arguments` 是模型填好的参数，通过 `JSON.stringify` 转成字符串形式交给 API。

第三个分支处理 `message.role === "tool"`。如果这是一条工具结果消息，就翻译成 `type: "function_call_output"`，用 `call_id: message.toolCallId` 告诉 API“这个结果对应哪一次工具调用”，再把结果内容放进 `output` 字段。

所以这段代码的本质是：**把 Agent 内部的三类消息，重新打包成 OpenAI Responses API 认得的三种记录**。用户消息变成 `message`，模型回答变成 `message` 加可能的 `function_call`，工具结果变成 `function_call_output`。这样 Agent 内部始终只用统一的 `AgentMessage`，供应商格式的差异全被关在这段翻译逻辑里。

这个转换层很重要。Agent Loop 只需要认识 `AgentMessage`，不用认识 Responses API、Chat Completions API 或 Anthropic API。以后要新增其他的 provider 支持，只需要实现新的 `LlmClient`，不需要重写整个 Agent Loop。

> 通俗解释：可以把它想象成“统一的快递单”和“各家快递公司的不同表单”。Agent 内部只认自己那一种快递单；`LlmClient` 负责把这种快递单翻译成 OpenAI 要的格式，或者反过来把 OpenAI 的回复翻译回 Agent 认识的格式。以后换一家快递公司，只换翻译员，不换收件流程。

当前 OpenAI Responses Client 同时支持 streaming。它会把 SSE（一种“服务器持续往客户端吐数据”的通信方式。） 事件归一成内部事件：

| Responses stream event | 内部事件 |
|---|---|
| `response.output_text.delta` | `text_delta` |
| `response.reasoning_summary_text.delta` | `thinking_delta` |
| `response.function_call_arguments.delta` | `tool_call_delta` |
| `response.completed` | `done` |

因为每个 `delta` 都对应同一个回答的不同部分，Agent 可以一边接收 `text_delta`，一边把碎片累积起来；等收到 `done`，说明全部内容已经到齐，就能拼出一个完整的 `AssistantMessage`。这个过程对 Agent 是透明的：它仍然只等待“最终答案”，只不过这个最终答案是边收边拼出来的。

所以结论就是：**不管是 streaming 还是非 streaming，Agent 最终拿到的都是同一个 `AssistantMessage`，只是交付过程不同。** 既然 Agent 只需要面对这个统一结果，那它的循环逻辑就只用写一套：调用模型、拿最终消息、检查工具调用、继续下一轮。真正区分流式和非流式的，只发生在 `LlmClient` 内部，不需要污染 Agent Loop。

> `delta` 是“一小块增量”的意思，所以 `text_delta` 就是“新吐出来的一小段文字”。

---

## 3. Tool System：让错误也进入循环

工具注册表很简单：

```typescript
export class ToolRegistry {
  private readonly tools = new Map<string, AgentTool>();

  register(tool: AgentTool): void {
    if (this.tools.has(tool.name)) {
      throw new Error(`Tool already registered: ${tool.name}`);
    }
    this.tools.set(tool.name, tool);
  }

  get(name: string): AgentTool | undefined {
    return this.tools.get(name);
  }

  toLlmToolSpecs(): LlmToolSpec[] {
    return this.list().map((tool) => ({
      name: tool.name,
      description: tool.description,
      parameters: tool.parameters
    }));
  }
}
```

`ToolRegistry` 是 Agent 的“工具注册表”，它的作用就是把所有工具集中管理起来，让 Agent 能按名字找到工具，也能把工具列表转换给模型看。类里面用 `private readonly tools = new Map<string, AgentTool>()` 保存一张“工具名 → 工具对象”的字典：`private` 表示这张表只能由注册表自己操作，外部不能随便改；`readonly` 表示这个字典的引用不会在创建后被替换掉；`Map<string, AgentTool>` 则规定了键是工具名字，值是符合 `AgentTool` 形状的工具对象。

`register(tool: AgentTool)` 是登记工具的方法。它先检查 `this.tools.has(tool.name)`，也就是看看这个名字有没有被登记过；如果已经存在，就执行 `throw new Error(...)` 主动报错，防止两个工具抢同一个名字，因为模型点名时必须保证名字唯一。如果名字没问题，就调用 `this.tools.set(tool.name, tool)`，把“名字 → 工具”这对关系放进字典里。

`get(name: string)` 是查找工具的方法，返回 `AgentTool | undefined`，意思是“能找到就返回工具，找不到就返回 `undefined`”。它内部直接执行 `return this.tools.get(name)`，也就是从字典里按名字取工具。`toLlmToolSpecs()` 是“生成给模型看的工具说明书”的方法，返回一个 `LlmToolSpec[]`。它先通过 `this.list()` 拿到当前所有工具，再用 `.map(...)` 把每个工具都转换成一个精简对象，只保留模型需要知道的三样东西：`name`、`description`、`parameters`。

所以这段代码的本质是：**一个工具管理员**。它负责登记工具、防止重名、按名字查找，以及在调用模型前，把完整的工具对象压缩成模型能看懂的精简说明书。模型看到的不是工具的完整实现，只是一个“这个工具叫什么、有什么用、参数怎么填”的目录。

执行器也保持了最小：

```typescript
export class ToolExecutor {
  constructor(private readonly registry: ToolRegistry) {}

  async execute(toolCall: ToolCall, signal?: AbortSignal): Promise<ToolResultMessage> {
    const tool = this.registry.get(toolCall.name);

    if (!tool) {
      return toToolResultMessage(toolCall, {
        content: `Tool not found: ${toolCall.name}`,
        isError: true
      });
    }

    try {
      validateArguments(tool.parameters, toolCall.arguments);
      const result = await tool.execute(toolCall.arguments, {
        toolCallId: toolCall.id,
        signal
      });
      return toToolResultMessage(toolCall, result);
    } catch (error) {
      return toToolResultMessage(toolCall, {
        content: error instanceof Error ? error.message : String(error),
        isError: true
      });
    }
  }
}
```

`ToolExecutor` 是 Agent 的“工具执行员”，它的职责就是拿到模型发出的 `toolCall`，真正去执行对应的工具，并且无论成功还是失败，都把结果包装成一条 `ToolResultMessage` 交回给 Agent Loop。它通过 `constructor(private readonly registry: ToolRegistry)` 在创建时保存一份工具注册表，之后执行时才能根据工具名查找到真正的工具。`execute(toolCall: ToolCall, signal?: AbortSignal)` 是执行入口：`toolCall` 是模型发出的“我要调用这个工具”的请求，里面包含工具名和参数；`signal` 是可选取消信号，用户中途取消时可以通知执行过程停止。方法开头先执行 `const tool = this.registry.get(toolCall.name)`，也就是按模型点名的工具名去注册表里查；如果 `!tool`，说明这个工具根本不存在，程序不会直接崩溃，而是调用 `toToolResultMessage(toolCall, { content: "Tool not found: ...", isError: true })`，生成一条“找不到工具”的错误结果消息，并把 `isError` 标记为 `true`，让模型下一轮能看到这个失败原因。如果工具存在，就进入 `try` 块：先调用 `validateArguments(tool.parameters, toolCall.arguments)` 检查模型提交的参数是否符合工具规定的 `schema`，不符合就会抛错；符合后执行 `await tool.execute(toolCall.arguments, { toolCallId: toolCall.id, signal })`，真正让工具干活，并把这次工具调用的 ID 和取消信号传给工具。工具顺利返回后，再通过 `toToolResultMessage(toolCall, result)` 把真实结果包装成标准消息。如果 `try` 块里任何一步出错，比如参数不对、工具内部抛异常，都会被 `catch (error)` 接住，程序不会让整个 Agent 中断，而是把错误内容 `error.message` 或转换后的 `String(error)` 包成一条 `isError: true` 的消息返回。所以这段代码的本质是：**不管工具成功还是失败，都把它变成模型能看到的 observation**。成功就告诉模型“结果是什么”，失败就告诉模型“哪里错了”，模型因此有机会修正参数、换工具或向用户解释原因，而不是让宿主程序直接崩溃。这正是第一篇里说的“失败是第一等公民”。

这里有一个小但关键的设计：工具不存在、参数错误、执行抛错，都不会直接中断 Agent。它们会变成一条 `role: "tool"` 且 `isError: true` 的消息，被写回 history。

这就是第一篇里说的原则：**Failures as First-Class Citizens。**

对模型来说，错误不是外部异常，而是一条 observation。模型可以基于它修正参数、换工具、或者告诉用户失败原因。

---

## 示例工具

当前内置了两个教学工具：`calculator` 和 `get_weather`。

`calculator` 的定义是：

```typescript
export const calculatorTool: AgentTool = {
  name: "calculator",
  description: "Evaluate a basic arithmetic expression.",
  parameters: {
    type: "object",
    properties: {
      expression: {
        type: "string",
        description: "Arithmetic expression using numbers, parentheses, +, -, *, /, %, and **."
      }
    },
    required: ["expression"],
    additionalProperties: false
  },
  execute(args) {
    const expression = readStringProperty(args, "expression");

    if (!/^[\d\s+\-*/().%]+$/.test(expression)) {
      throw new Error("Calculator only accepts numbers, whitespace, parentheses, and arithmetic operators.");
    }

    const value = Function(`"use strict"; return (${expression});`)() as unknown;

    if (typeof value !== "number" || !Number.isFinite(value)) {
      throw new Error("Expression did not produce a finite number.");
    }

    return { content: String(value) };
  }
};
```

`calculatorTool` 是一个符合 `AgentTool` 标准形状的具体工具对象，它的作用就是给 Agent 提供一台“计算器”。`name` 是工具名，模型通过 `calculator` 这个名字来点名调用它；`description` 是给模型看的说明，让模型知道这个工具适合处理 `(123 + 456) * 789` 这类算术表达式。`parameters` 用 `JsonSchema` 规定了模型提交参数时的格式：模型必须提交一个对象，里面只能有一个 `expression` 字段，类型必须是字符串，内容必须是“只包含数字、空格、括号、`+ - * / %` 和点号”的算术式子；`required: ["expression"]` 表示这个参数必填，`additionalProperties: false` 表示模型不能提交 `expression` 之外的多余字段。真正的执行逻辑放在 `execute(args)` 里：它先通过 `readStringProperty(args, "expression")` 取出模型提交的 `expression` 字符串，然后用 `if (!/^[\d\s+\-*/().%]+$/.test(expression))` 做安全检查，只允许出现数字、空格、括号和这些数学运算符，一旦出现字母或其他内容就 `throw new Error(...)`，防止不安全的内容混进表达式。检查通过后，它用 ``Function(`"use strict"; return (${expression});`)()``把字符串当成一个真正的数学表达式计算出来，得到 `value`；接着再用 `if (typeof value !== "number" || !Number.isFinite(value))`做二次检查，如果结果不是数字或者不是有限数字，比如NaN或无穷大，就直接报错。只有全部检查通过，才返回 `{ content: String(value) }`，也就是把计算结果转成字符串，包装成一条 `ToolResultMessage` 交给 Agent Loop，让模型下一轮能看到真实计算结果并继续推理。所以这段代码本身不是 Agent 循环，而是一个具体的工具实现：它向系统声明“我有一个计算器工具”，并定义了这个工具“参数怎么填、怎么算、怎么返回”。

这个工具写得很简单，主要是为了能用就行，重点是跑通工具调用链路：

```text
tool schema -> model tool call -> tool execution -> tool result message -> next model request
```

简单说，`schema` 告诉模型“你只能提交一个叫 `expression` 的文本参数，里面只能放数字、括号和加减乘除等符号”。模型只要提交符合这个表单的请求，宿主程序就会真正计算，然后把数字结果作为 observation 还给模型。

---

## 运行示例

这个简单的 demo 可以一行命令启动。下面这次测试使用的是兼容 OpenAI Responses API 的代理端点和 `gpt-5.5`：

```bash
OPENAI_BASE_URL="https://xxx" \
OPENAI_MODEL="gpt-5.5" \
OPENAI_API_KEY="..." \
AGENT_REASONING_EFFORT="xhigh" \
npm run demo -- "Calculate (123 + 456) * 789123123. then reply who are you"
```

实际输出如下：

```text
[turn 1]

[thinking]
**Calculating arithmetic accurately**
I need to respond to the user by calculating the expression they provided,
which is (123 + 456) * 789,123,123. ...

[tool args] calculator {"expression":"(123 + 456) * 789123123"}
[tool] calculator {"expression":"(123 + 456) * 789123123"}
[observation] 456902288217

[turn 2]
456902288217
I’m an AI assistant.
```

这个输出能清楚看到两轮循环：

第一轮，模型没有直接回答，而是先输出 reasoning summary，然后流式生成 `calculator` 的工具参数。Agent 执行工具后得到 observation：`456902288217`。

第二轮，模型看到工具 observation，再生成最终回答：先给出计算结果，然后回答 “I’m an AI assistant.”。

---

## 我们从现有项目学到了什么？

这一版虽然叫“最小 Agent Loop”，但它不是最原始的 while loop。它在几个地方提前保留了扩展点。

### 1. 流式和非流式共用同一个 loop

```typescript
if (!isStreamingLlmClient(this.llm)) {
  return this.llm.complete(request);
}

for await (const event of this.llm.stream(request)) {
  // thinking_delta / text_delta / tool_call_delta / done
}
```

`isStreamingLlmClient(this.llm)` 是在检查当前这个 `LlmClient` 是否具有流式能力，前面的 `!` 表示“如果不支持”。如果不支持，就走非流式路径，直接 `return this.llm.complete(request)`，意思是把 `request` 发给模型，等模型完整生成完，再一次性返回一个完整的 `AssistantMessage`。<br>如果支持流式，就不走 `return`，而是进入下面的 `for await (const event of this.llm.stream(request))`。这里的 `this.llm.stream(request)` 返回一个事件流，`for await` 会一条一条地接收事件：模型每吐出一小段内容，就产生一个 `event`，程序可以立即处理，而不需要等全部生成完。注释里的四种事件就是流式过程中可能出现的关键增量：`thinking_delta` 是模型的思考片段，`text_delta` 是正文片段，`tool_call_delta` 是工具调用参数片段，`done` 表示整个回答已经结束。所以这段代码的本质是一个“分岔口”：先检查模型客户端有没有流式能力，没有就用 `complete()` 一次拿完整答案，有就用 `stream()` 边生成边接收；但无论走哪条路，最终都会得到一个完整的模型回答，因此 Agent Loop 本身的循环逻辑不需要为流式和非流式各写一套。

streaming 只是 LLM Client 的增强能力。Agent Loop 仍然只等待一个最终 `AssistantMessage` 来决定是否执行工具。

### 2. 工具可以并行执行，但历史顺序稳定

`executeToolCalls` 支持两种策略：

```typescript
const mustRunSequentially =
  this.toolExecution === "sequential" ||
  toolCalls.some((toolCall) => this.tools.get(toolCall.name)?.executionMode === "sequential");

if (mustRunSequentially) {
  // one by one
}

const results = await Promise.all(
  toolCalls.map(async (toolCall) => this.executor.execute(toolCall, signal))
);
```

这段代码解决的是“这一批工具到底该顺序执行还是并行执行”的问题。第一行 `const mustRunSequentially = this.toolExecution === "sequential" || toolCalls.some(...)` 是在计算一个布尔值，名字 `mustRunSequentially` 就是“这一批是否必须排队执行”。它先检查 `this.toolExecution === "sequential"`，也就是整个任务级默认策略是不是顺序执行；如果是，就直接判定必须顺序执行。如果不是，再用 `toolCalls.some((toolCall) => ...)` 检查这次模型请求的所有工具里，有没有任何一个工具声明自己必须顺序执行。这里的 `.some()` 意思是“只要有一个满足，结果就是 true”；对于每个 `toolCall`，它通过 `this.tools.get(toolCall.name)` 从工具注册表里找到对应的工具，再用 `?.executionMode === "sequential"` 查看这个工具自己声明的执行模式是不是 `sequential`。如果全局要求顺序，或者任何单个工具要求顺序，`mustRunSequentially` 就是 true，于是进入 `if (mustRunSequentially)` 分支，执行注释里的 `// one by one`，也就是一个工具一个工具地排队跑，前一个完成才轮到下一个。如果没有触发顺序条件，程序就跳过 `if`，走到 `const results = await Promise.all(toolCalls.map(async (toolCall) => this.executor.execute(toolCall, signal)))`。这里的 `toolCalls.map(...)` 会把每个 `toolCall` 都转换成一个“执行这个工具”的异步任务，然后 `Promise.all` 让这些任务同时开始执行，并且等待全部完成；`signal` 会被传给每个工具，用来支持中途取消。`Promise.all` 还有一个很关键的保证：结果数组 `results` 的顺序和输入数组 `toolCalls` 的顺序一致，不会因为哪个工具先跑完就排在前面。

所以这段代码的本质就是：先判断“要不要排队”，如果要就一个接一个执行；如果不需要，就并行执行，但最终结果仍然按模型最初发出工具调用的顺序排列，保证模型看到的上下文顺序稳定。

如果模型一次请求多个互不依赖的工具，未来可以并发执行。但 `Promise.all` 的结果顺序和输入数组一致，所以写回 history 的顺序仍然稳定。Codex 和 Pi 的实现中都有这一部分：**性能可以并行，模型看到的上下文不能乱。**

> 通俗解释：并行执行像“同时点两份外卖”；但端上桌时必须按你下单的顺序摆好，否则模型会以为第二份才是第一份。上下文顺序一旦乱了，模型的推理就可能跟着乱。

### 3. 工具错误不会打断循环

工具错误被转换为：

```text
{
  role: "tool",
  toolCallId: toolCall.id,
  toolName: toolCall.name,
  content: "...error message...",
  isError: true
}
```

这段代码是“把工具错误变成一条普通历史消息”的示例，它不是一段执行逻辑，而是一个具体的 `ToolResultMessage` 对象，用来告诉模型：“刚才那一次工具调用失败了，原因是这个。”`role: "tool"` 表示这条消息在对话历史里属于工具角色，模型能区分出它不是用户说的，也不是模型自己说的，而是宿主程序执行工具后返回的观察结果；`toolCallId: toolCall.id` 记录的是这次工具调用对应的唯一编号，用来把结果和模型之前发出的某一次 `toolCall` 对应起来；`toolName: toolCall.name` 记录的是工具名，比如 `calculator` 或 `get_weather`，让模型知道失败的是哪个工具；`content: "...error message..."` 是真正给模型看的错误内容，可能是“Tool not found”“参数格式不对”“权限不足”这类信息；`isError: true` 是这个对象的关键标志，它表示“这是一条失败结果，而不是正常返回”。整个设计的核心是：工具失败时，程序不会直接抛异常把 Agent 弄崩溃，而是把失败信息包装成这条 `role: "tool"`、`isError: true` 的消息，然后写回 history，让模型在下一轮像看到普通 observation 一样看到失败原因。模型因此可以自己决定下一步怎么走：修正参数再试一次、换一个工具、或者直接向用户解释为什么失败。这就是“失败是第一等公民”的含义：错误不是程序外部的意外，而是模型可以阅读、可以推理、可以据此继续行动的上下文。

这让模型有机会“读到失败”，而不是让宿主程序直接抛异常结束。

在真实 Agent 中，这个细节非常重要。因为工具失败太常见了：文件不存在、命令退出码非零、网络请求 429、参数 schema 不匹配、权限不足。失败如果不进入上下文，模型就没有自我修正的机会。

> 通俗解释：把错误也写成一条普通消息，相当于让模型看到“刚才这步失败了，原因是这个”。模型可以换一种写法、换一个工具，或者直接告诉用户失败原因。这个设计叫做“失败是第一等公民”。

### 4. 事件系统先行

当前 Agent 支持两种事件消费方式：

```typescript
new Agent({
  onEvent(event) {
    // log, UI, SSE, WebSocket...
  }
});
```

也支持：

```typescript
for await (const event of agent.runEvents(input)) {
  // async iterable event stream
}
```

事件包括：

```text
agent_start
turn_start
thinking_delta
assistant_delta
tool_call_delta
message
tool_start
tool_end
turn_end
agent_end
```

这两段代码放在一起，是 Agent 事件系统的两种“接收方式”，它们都表示“外部程序可以知道 Agent 正在发生什么”，只是接入方式不同。<br>第一种是 `new Agent({ onEvent(event) { ... } })`：创建 Agent 时，把 `onEvent` 这个回调函数作为配置传进去，相当于提前告诉 Agent“每当发生一个事件，你就调用我这个函数，并把 `event` 交给我”。函数体里的注释 `// log, UI, SSE, WebSocket...` 表示：拿到 `event` 后，你可以把它写入日志、推给网页界面、转成 SSE 发给浏览器，或者通过 WebSocket 推给客户端。这个方式更像“把电话号码留给codex，codex主动打给你”。<br>第二种是 `for await (const event of agent.runEvents(input))`：调用 `agent.runEvents(input)` 启动 Agent，并让它返回一个事件流；`for await` 会在这个流上一条一条地接收事件，每来一个 `event`，循环体就处理一个，没来就先等着。这种方式更像“你打开收音机，广播来一段你听一段”。<br>两种方式收到的都是同一套事件，比如 `agent_start`、`turn_start`、`thinking_delta`、`tool_start`、`tool_end`、`agent_end` 等，区别只在于“Agent 主动推给你”还是“你主动去流里取”。而它们共同的优点是一致的：外部程序只需要订阅这些事件，就能实现进度显示、日志记录、调试、监控等能力，不需要修改 Agent Loop 内部逻辑。所以这两段代码是在展示同一个事件系统的两种消费接口：一种适合“回调式集成”，一种适合“异步流式处理”，但底层都是同一条 agent event stream。

这让最小实现天然可以接 CLI、Web UI、HTTP SSE 或调试日志。后续加可观测性时，不需要再把 Agent Loop 拆开重写。

### 5. Reasoning 配置被放在 LLM 边界

当前 Agent 支持：

```text
reasoning: {
  effort: "high",
  summary: "concise"
}
```

也支持单次运行关闭：

```text
await agent.run("...", { reasoning: false });
```

这两段代码放在一起，展示的是“推理配置怎么从 Agent 传到 LLM 边界”。第一段 `reasoning: { effort: "high", summary: "concise" }` 是一个通用配置对象：`effort: "high"` 表示这次让模型思考用力一点，也就是在回答前多花一些推理；`summary: "concise"` 表示模型对外展示的思考摘要要简洁，不要输出一长串推理过程。这里的 `reasoning` 不是 OpenAI 或 Anthropic 的专有字段，而是 Agent 自己定义的一个通用描述，意思是“我希望模型这次怎么想、怎么展示思考”。<br>第二段 `await agent.run("...", { reasoning: false })` 则是 Agent 的单次运行入口：用户输入是 `"..."`，`{ reasoning: false }` 表示这次运行不开启推理，也就是让模型不进入那种“先详细思考再回答”的模式，直接给出回答。这两段代码合在一起，说明 Agent 对推理的控制是分层的：Agent Loop 只需要输出一个通用的 `reasoning` 配置，比如“用高努力”还是“关闭”，然后把这份配置原样往下传；真正负责把 `effort`、`summary`、`false` 这些通用表达翻译成具体模型 API 字段的，是 `OpenAIResponsesClient` 这类 LLM Client。也就是说，Agent 不需要知道 OpenAI 的某个参数叫什么、Anthropic 的某个参数叫什么，它只表达“这次思考用力一点”或“这次不用思考”，翻译工作全部收在 LLM 边界里。所以这段代码展示的正是“Reasoning 配置放在 LLM 边界”的意思：上层保留通用语义，下层负责供应商适配。

> 通俗解释：“Reasoning 配置放在 LLM 边界”的意思是：Agent 只知道“这次任务思考用力一点还是轻一点”，具体这个要求怎么翻译成 OpenAI 的字段，由翻译层负责。

---

## 下一节做什么？

下一篇会实现**上下文管理器（Context Manager）**。

现在的 Agent 每一轮都把完整 `messages` 原样交给模型，这在 demo 里没问题，但真实任务很快会遇到三个问题：

- **上下文窗口爆炸**：工具日志、错误堆栈、长文件内容会迅速占满 token。
- **注意力漂移**：模型看到的信息太多，反而找不到当前最关键的目标和约束。
- **缓存不友好**：如果每轮 prompt 的前部不稳定，就很难命中 prompt cache。

所以第三篇会在当前 `Agent Loop -> LLM Client` 之间插入一个新模块：

```text
messages
  -> Context Manager
  -> model-ready context
  -> LLM Client
```

它会负责：

- 控制哪些历史进入模型。
- 对工具结果做截断和摘要。
- 固定 system prompt、工具列表等稳定前缀。
- 把当前目标、最近 observation、关键约束放到更容易被模型注意到的位置。

到那一步，我们就开始从“能跑的 Agent”进入“能跑长任务的 Agent”。

当然，我们现在的 Agent 还没有塞满上下文的能力，所以下一节中也会同步开发更多基础工具，让 Agent 有更多感知并影响世界的能力，获取到更多上下文。

> 通俗解释：这一课的问题是“每次把全部历史原样丢给模型”。短对话没问题，但真实任务中历史会越来越长：一个报错日志就可能占掉很大空间。上下文管理器就像一个“精装修的书桌”，决定桌上放哪几份文件、哪些收进抽屉、哪些压成摘要。

---

## 小结

第二篇完成的是 Agent 的最小生命体征：模型会思考、工具能执行、结果能回填、循环能继续、答案能终止。它没有复杂 Harness，但已经具备 Agent 的核心结构。Codex 和 Pi 的生产实现都可以拆成这个最小循环：模型请求动作，宿主执行动作，观察结果回到模型，直到模型给出最终回答。后续所有模块，都会围绕这个循环继续生长。

一句话记住这一课：

> **Agent = 循环。循环 = 模型想一步，程序做一步，结果看一步，再让模型想下一步，直到它说“完成”。**

## 参考资料

- 原文：[Build An Agent From Scratch [2]：最小 Agent Loop](https://www.tritium.work/2026/06/08/Build%20An%20Agent%20From%20Scratch%20%5B2%5D%EF%BC%9A%E6%9C%80%E5%B0%8F%20Agent%20Loop/)
