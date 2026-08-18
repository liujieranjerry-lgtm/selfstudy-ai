# 06 — Build An Agent From Scratch [2]：最小 Agent Loop

> 本文是 selfstudy-ai 自学笔记的第 6 篇。<br>
> 目标：看懂一个“最小但能跑起来”的 Agent 是由哪几块拼出来的：Agent Loop、LLM Client、Tool System，以及它们之间怎样通过消息历史互相配合。

> 原文：[Build An Agent From Scratch \[2\]：最小 Agent Loop](https://www.tritium.work/2026/06/08/Build%20An%20Agent%20From%20Scratch%20%5B2%5D%EF%BC%9A%E6%9C%80%E5%B0%8F%20Agent%20Loop/)

> 这是「从零搭建 Agent」系列的第二篇。上一篇先搭了理论骨架：Agent Loop 是心脏，Harness 是围绕这个循环做上下文工程和注意力管理的系统。从这一篇开始，我们把理论实践到代码里：先不做复杂的 Harness，只实现一个最小但能跑起来的 Agent Loop。

同步项目地址 [https://github.com/Tritium0041/Singularity](https://github.com/Tritium0041/Singularity)，当前进度位于 [https://github.com/Tritium0041/Singularity/commit/223fa936b28f24c1b2d6629f924057d76b9f5926](https://github.com/Tritium0041/Singularity/commit/223fa936b28f24c1b2d6629f924057d76b9f5926)


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

**Responses API**：这是 OpenAI 比较新的接口，设计思路更像“给 Agent 用”，而不是单纯给聊天用。它会返回一个更完整的 `response` 对象，能表达推理内容、文本、工具调用、工具结果等多种信息；同时支持状态管理、工具调用、多模态和推理参数。程序不必自己拼一大堆历史记录，可以把更多状态交给 API 处理，因此它更适合做 Agent Loop 这类需要反复“模型思考 → 工具执行 → 结果回填”的场景。

**Chat Completions API**：这是 OpenAI 比较早的聊天接口，核心模型就是“你给我一段对话历史，我还你一个回答”。程序需要自己维护整段历史，每次请求都把完整的 `messages` 列表发给模型，再从返回结果里挑出模型文字或工具调用。它简单直接，很多老系统、兼容层、第三方代理都用它，但在复杂 Agent 场景里，状态管理和工具链路都需要程序自己多操心。

**Anthropic API（Messages API）**：这是 Claude 的原生接口，来自 Anthropic。它和 OpenAI 的接口不是同一套格式：消息角色、请求字段、工具定义、流式事件都有自己的命名和结构。比如它用 `system`、`user`、`assistant` 这类消息，工具调用和流式事件也和 OpenAI 不一样。如果 Agent 想接入 Claude，不能把 OpenAI 的请求原样发过去，必须有一个新的 `LlmClient` 来翻译。

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

类型的作用，是提前告诉程序“这里应该放文字、那里应该放数字、这个变量代表一种什么形状的对象”。这样写代码时更容易发现错误，也更容易让多人协作。

> 通俗解释：JavaScript 像“普通便签”，什么都能往上写；TypeScript 像“带格子、带标签的表格”，每一格该填什么都写清楚。本文里那些 `LlmClient`、`AgentTool` 之类的形状，就是用 TypeScript 写的“表格规范”。

#### 6. hooks 里的“外部程序”指什么？

这里的“外部程序”不是模型，也不是工具，而是** Agent 主程序之外、想观察或控制 Agent 的其他程序**。

例如：一个网页界面、一个命令行工具、一个日志系统、一个监控面板。它们不想改写 Agent 内部的循环，只想知道“现在进行到哪一步了”，或者在某些时刻插入自己的逻辑。hooks 就是给这些外部程序预留的“挂钩点”。

> 通俗解释：Agent 像一台自动售货机，hooks 是它身上的外接插口。售货机不用拆开重装，外部设备插上插口就能读到“正在出货”“出货完成”这类状态。


---


## 同类 Agent 是怎么做的？

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

**第二，工具错误也是上下文。** 在 `codex-rs/core/src/tools/parallel.rs` 里，非 fatal 的工具错误会被转换成失败的 function call output，而不是直接让整个 turn 崩掉。也就是说，`command failed`、`tool not found`、`permission denied` 这类信息都应该成为模型可见的 observation。

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

**第二，事件流是一等接口。** Pi 会发出 `agent_start`、`turn_start`、`message_start`、`tool_execution_start`、`tool_execution_end`、`agent_end` 这类事件。这样 CLI、TUI、Web UI、日志系统都可以订阅同一条 agent event stream。

> 通俗解释：事件流就像广播电台。Agent 每做一步都会广播“我开始干活了”“我在调用工具了”“工具完成了”；任何界面都可以听这个广播，不需要改 Agent 本身的逻辑。

拆开讲“全局”和“单个工具”：

- `toolExecution` 是任务级的默认策略，可以理解成“这场任务里所有工具调用默认怎么执行”。
- 每个工具自己的 `executionMode` 是“这个工具个人的偏好”，可以覆盖全局默认值。
- 如果全局是 `parallel`，但某一次要调用的工具里有一个声明自己是 `sequential`，那么这一批工具就降级成顺序执行，不能并行。

`sequential` 和 `parallel` 的区别：

| 模式 | 执行方式 | 类似场景 |
|---|---|---|
| sequential | 一个一个执行，前一个结束才轮到后一个 | 排队做核酸，一个人没做完下一个人不能开始 |
| parallel | 多个工具同时开始执行 | 同时让三个人分头去买菜，买完再汇总 |

之所以“任一工具要求顺序就整体顺序”，是因为并行可能会造成依赖问题：如果工具 B 需要工具 A 的结果，而 B 提前跑，就会拿到不完整的信息。最安全的做法是：只要有一个工具说“我不能并行”，整批就乖乖排队。

所以我们这一版的实现策略很明确：

- 学 Codex 的调用逻辑：工具结果回填、工具错误回填、并行执行但顺序写回。
- 学 Pi 的形态：显式 TypeScript loop、清晰的 LLM 边界、事件驱动。
- 暂时不做复杂 Harness。

拆开讲“显式 TypeScript loop”：

“显式”的意思是：循环结构在代码里清清楚楚，你能直接看到 `while` 或 `for` 在反复执行“问模型、看工具调用、执行工具、写回历史”。它不靠隐藏魔法，不把循环藏在别的地方。

“TypeScript loop”就是指这个循环是用 TypeScript 写的，并且借用了 TypeScript 的类型系统，把模型、工具、消息都定义成有清晰形状的对象。

拆开讲“LLM 边界清晰”：

边界是指“Agent 自己的逻辑”和“模型供应商的细节”之间有一道清楚的分界线。Agent Loop 只使用统一的 `complete()` / `stream()` 和统一的 `AssistantMessage`，不直接处理 OpenAI 的字段、Anthropic 的字段、流式事件的细节。所有供应商特有的翻译都收在 `LlmClient` 里。

> 通俗解释：Agent Loop 是“老板”，只负责安排流程；`LlmClient` 是“翻译秘书”，负责把老板的话翻译成不同公司的格式。老板不需要懂每家公司的方言，这就是边界清晰。


---


## 我们的实现结构

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

Agent 对象不关心 OpenAI Responses API 的具体 payload，也不关心工具函数内部怎么执行。它只负责整体循环。

模型调用被压到 `LlmClient`：

```ts
export interface LlmClient {
  complete(request: LlmRequest): Promise<AssistantMessage>;
}

export interface StreamingLlmClient extends LlmClient {
  stream(request: LlmRequest): AsyncIterable<LlmStreamEvent>;
}
```

工具调用被压到 `ToolRegistry` 和 `ToolExecutor`：

```ts
export type AgentTool = {
  name: string;
  description: string;
  parameters: JsonSchema;
  executionMode?: "sequential" | "parallel";
  execute(args: unknown, context: ToolExecutionContext): Promise<ToolResult> | ToolResult;
};
```

于是 Agent Loop 本身可以保持很小。

> 通俗解释：这里最关键的不是语法，而是“边界”。`LlmClient` 只负责和模型说话；`ToolRegistry` 只负责管理有哪些工具；`ToolExecutor` 只负责执行工具。Agent Loop 本身不亲自做这些事，它只负责喊“开始”“下一轮”“结束”。这样以后换模型、换工具，都不用重写整辆车。

#### 第一段代码：`LlmClient` 的两种接口，逐行看

```ts
export interface LlmClient {
  complete(request: LlmRequest): Promise<AssistantMessage>;
}

export interface StreamingLlmClient extends LlmClient {
  stream(request: LlmRequest): AsyncIterable<LlmStreamEvent>;
}
```

逐行拆解：

1. `export interface LlmClient {`：定义一个公开的“合同”，名字叫 `LlmClient`。它不写具体实现，只规定“一个能调用模型的类，必须长成什么样”。
2. `complete(request: LlmRequest): Promise<AssistantMessage>;`：规定这个接口必须有一个 `complete` 方法。它接收一个统一格式的请求 `LlmRequest`，返回一个 `Promise`，也就是“以后会拿到一个结果”的承诺；承诺最终交付的东西是一个 `AssistantMessage`。
3. `export interface StreamingLlmClient extends LlmClient {`：定义 `StreamingLlmClient`，它继承 `LlmClient`，所以它一定也具备 `complete` 方法，同时再增加流式能力。
4. `stream(request: LlmRequest): AsyncIterable<LlmStreamEvent>;`：规定它必须有一个 `stream` 方法。它也接收 `LlmRequest`，但返回的不是一次性答案，而是一个可以一条一条读取的事件流，每条事件是一个 `LlmStreamEvent`。

> 通俗解释：`interface` 是“合同”，`Promise` 是“承诺”，`AsyncIterable` 是“可以一边等一边逐个读取的清单”。普通接口说“你一次性把答案给我”；流式接口说“你把答案切成小块，边生成边给我”。

#### 第二段代码：`AgentTool` 这个工具的标准形状，逐行看

```ts
export type AgentTool = {
  name: string;
  description: string;
  parameters: JsonSchema;
  executionMode?: "sequential" | "parallel";
  execute(args: unknown, context: ToolExecutionContext): Promise<ToolResult> | ToolResult;
};
```

逐行拆解：

1. `export type AgentTool = {`：定义一个公开的类型，名字叫 `AgentTool`，意思是“凡是工具，都必须长成这样”。
2. `name: string;`：工具的名字，用来让模型点名，也用来注册、查找。
3. `description: string;`：给模型看的工具介绍，相当于“招聘启事”，告诉模型这个工具是干什么的。
4. `parameters: JsonSchema;`：工具参数的“填写表单”，用 `JsonSchema` 这种标准格式描述哪些参数允许填、哪些必填、格式是什么。
5. `executionMode?: "sequential" | "parallel";`：可选字段，表示这个工具是“只能排队执行”还是“可以并行执行”。`?` 的意思是“可以不填”，不填就听全局默认。
6. `execute(args: unknown, context: ToolExecutionContext): Promise<ToolResult> | ToolResult;`：工具真正干活的方法。它接收模型提交的参数 `args` 和上下文 `context`；可以立刻返回 `ToolResult`，也可以返回一个“以后会有结果”的 `Promise<ToolResult>`。

> 通俗解释：`AgentTool` 就像一张“工具员工登记表”：姓名、简介、要填的申请表、能不能和别人同时干活，以及他真正干活的方法。`unknown` 表示参数一开始不知道是什么，等运行后再检查。


---


## Agent Loop 核心代码

当前最小循环在 `src/agent/agent-loop.ts` 的 `runInternal` 里。精简后是这样：

```ts
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

这段代码就是 Observe / Think / Act（aka reAct）的工程版本：

| 理论概念 | 代码对应 |
|---|---|
| Observe | `messages` 里已有的 user、assistant、tool result |
| Think | `completeAssistant(...)` 调用模型 |
| Act | `executeToolCalls(...)` 执行模型请求的工具 |
| Observe again | `this.messages.push(...toolResults)` 将工具结果写回历史 |
| Stop | assistant 没有 tool call，或达到 maxTurns |

> 通俗解释：`maxTurns` 是“最多允许循环多少轮”，防止模型陷入无限循环。`messages` 是这一轮任务的全部历史；每一轮模型看到的都是当前完整历史。`toolCalls.length === 0` 的意思是“模型这次没有要调用工具”，那就代表它可以给出最终答案了。

注意这里的 `messages: [...this.messages]`，每一轮模型看到的是当前完整 history。工具结果作为 `role: "tool"` 的消息存在，所以模型能基于上一次 action 的 observation 继续行动。

#### 长代码逐行拆解

这段代码是整套 Agent 循环最核心的一段。我们按“程序从进入函数到最后结束”的顺序，一行一行看：

```ts
private async runInternal(
  input: string,
  options: AgentRunOptions = {}
): Promise<AgentRunResult> {
```

1. `private async runInternal(...)`：这是一个内部方法。`private` 表示它只在 Agent 内部被调用，不对外暴露；`async` 表示这个方法内部会等待模型或工具返回，可以边等边做下一步。
2. `input: string`：用户这次输入的内容，通常是一句话。
3. `options: AgentRunOptions = {}`：本次运行的附加设置。`= {}` 表示如果不传，就当它是一份空设置。
4. `: Promise<AgentRunResult>`：方法最终会返回一个“以后会到手的运行结果”。

```ts
  const maxTurns = options.maxTurns ?? this.maxTurns;
  const userMessage: AgentMessage = { role: "user", content: input };
  this.messages.push(userMessage);
```

5. `const maxTurns = options.maxTurns ?? this.maxTurns;`：先决定最多能循环多少轮。`??` 的意思是“如果左边有值就用左边，如果左边为空就用右边”。也就是说，本次调用如果专门设置了轮数，就听本次的；没设置就用 Agent 默认值。
6. `const userMessage: AgentMessage = { role: "user", content: input };`：把用户输入包成一条 Agent 内部统一认识的消息，角色是 `user`，内容是输入文本。
7. `this.messages.push(userMessage);`：把这条用户消息追加到当前任务的历史里。从这一刻起，它也是模型下一轮会看到的内容。

```ts
  let lastAssistant: AssistantMessage | undefined;

  for (let turn = 1; turn <= maxTurns; turn += 1) {
```

8. `let lastAssistant: AssistantMessage | undefined;`：先准备一个变量，用来记住“最近一次模型回答”。之所以可能为空，是因为如果第一轮就出问题，不一定拿得到答案。
9. `for (let turn = 1; turn <= maxTurns; turn += 1)`：建立循环。从第 1 轮开始，每跑完一轮 `turn` 加 1，直到超过 `maxTurns` 为止。这就是“最多允许跑多少轮”的保护。

```ts
    const assistant = await this.completeAssistant(turn, {
      model: this.model,
      systemPrompt: this.systemPrompt,
      messages: [...this.messages],
      tools: this.tools.toLlmToolSpecs(),
      reasoning: options.reasoning ?? this.reasoning,
      signal: options.signal
    });
```

10. `const assistant = await this.completeAssistant(...)`：调用 Agent 内部的“让模型回答一次”的方法，并等待它返回。`await` 的意思是“这里会花时间，我等它完成再继续”。
11. `model: this.model`：告诉方法用哪个模型。
12. `systemPrompt: this.systemPrompt`：把系统提示词也传进去，相当于“模型一直要遵守的总规则”。
13. `messages: [...this.messages]`：把当前完整历史复制一份给模型。`[...]` 是“把数组展开成新数组”，防止模型看到的内容和内部历史互相干扰。
14. `tools: this.tools.toLlmToolSpecs()`：把工具列表转换成模型能看懂的“工具说明书”。
15. `reasoning: options.reasoning ?? this.reasoning`：决定这次思考用力程度；本次设置优先，否则用默认。
16. `signal: options.signal`：把取消信号传下去，让模型知道用户是否已经中途取消。

```ts
    lastAssistant = assistant;
    this.messages.push(assistant);

    const toolCalls = assistant.toolCalls ?? [];
    if (toolCalls.length === 0) {
      return this.buildResult(assistant.content, turn, "final");
    }
```

17. `lastAssistant = assistant;`：把这次模型回答记进变量，防止后面循环结束但拿不到答案。
18. `this.messages.push(assistant);`：把模型回答追加到历史里。模型说过的话，之后也会成为它自己看到的上下文。
19. `const toolCalls = assistant.toolCalls ?? [];`：检查模型有没有请求调用工具。如果它这次没提任何工具，就得到一个空数组。
20. `if (toolCalls.length === 0)`：如果模型没有要求调用工具，说明它已经可以直接给出最终答案。
21. `return this.buildResult(assistant.content, turn, "final");`：把模型这次的文字内容、轮次、状态 `final` 打包成结果返回，整个 turn loop 结束。

```ts
    const toolResults = await this.executeToolCalls(turn, toolCalls, options.signal);
    this.messages.push(...toolResults);
  }

  return this.buildResult(lastAssistant?.content ?? "", maxTurns, "max_turns");
}
```

22. `const toolResults = await this.executeToolCalls(turn, toolCalls, options.signal);`：如果模型请求了工具，宿主程序就真的去执行这些工具，并等待所有结果返回。
23. `this.messages.push(...toolResults);`：把执行结果一条一条写回历史。这里的 `...` 表示“展开数组”，等于把每个结果分别追加进去，而不是把整个数组当成一条消息。
24. 回到 `for`：这一轮结束，`turn` 加 1，如果还没超过 `maxTurns`，模型就能看到刚写回的工具结果，继续下一轮。
25. `return this.buildResult(lastAssistant?.content ?? "", maxTurns, "max_turns");`：如果循环次数已经用完，但模型还没给出最终答案，就强制结束，状态标记为 `max_turns`。`?.` 的意思是“如果 `lastAssistant` 存在才读它的 content；不存在就返回空字符串”，避免程序因为没有答案而崩溃。

> 通俗解释：整段代码就是“让模型想一次；如果它说要工具，宿主就去执行并把结果写进历史；再让模型想一次；直到它给最终回答或轮数用完”。


---


## LLM Client：隔离模型供应商

我们的 OpenAI 格式接口接入在 `src/llm/openai-responses-client.ts`。它做两件事：

- 把内部消息结构转换成 Responses API 的 `input`。
- 把 Responses API 的输出转换回内部 `AssistantMessage`。

内部消息到 Responses input 的转换逻辑大概是：

```ts
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

这个转换层很重要。Agent Loop 只需要认识 `AgentMessage`，不用认识 Responses API、Chat Completions API 或 Anthropic API。以后要新增其他的 provider 支持，只需要实现新的 `LlmClient`，不需要重写整个 Agent Loop。

> 通俗解释：可以把它想象成“统一的快递单”和“各家快递公司的不同表单”。Agent 内部只认自己那一种快递单；`LlmClient` 负责把这种快递单翻译成 OpenAI 要的格式，或者反过来把 OpenAI 的回复翻译回 Agent 认识的格式。以后换一家快递公司，只换翻译员，不换收件流程。

这里直接回答你后面可能会问的问题：**“翻译层”就是“转换层”**。

这两个词说的是同一个东西。文章里说“转换层很重要”，说的就是 `LlmClient` / `OpenAIResponsesClient` 干的活：把 Agent 内部统一的 `AgentMessage` 翻译成 OpenAI Responses API 认得的 `input`，再把 OpenAI 返回的内容翻译回 `AssistantMessage`。你可以把 `LlmClient` 理解成“翻译员”，把“转换层”理解成“翻译员所在的岗位”。

上面的转换代码也可以逐行看：

1. `if (message.role === "user")`：如果这条内部消息是用户消息，就把它翻译成 Responses API 的 `input` 里一条 `type: "message"`、`role: "user"` 的记录，正文放在 `input_text` 里。
2. `if (message.role === "assistant")`：如果这条内部消息是模型回答，先翻译成 `type: "message"`、`role: "assistant"` 的记录；如果这次模型还请求了工具调用，就再把每个工具调用翻译成 `type: "function_call"` 的记录，并带上调用 ID、工具名、参数。
3. `if (message.role === "tool")`：如果这条内部消息是工具结果，就翻译成 `type: "function_call_output"`，用 `call_id` 告诉 API“这是哪一次工具调用的结果”，再用 `output` 填上结果内容。

> 通俗解释：这套代码就是“拆包裹、重新打包”。Agent 内部是一种包裹，OpenAI 要的是另一种包裹；翻译层负责把每一件都塞进对方认得的盒子里，再贴上正确的标签。

当前 OpenAI Responses Client 同时支持 streaming。它会把 SSE 事件归一成内部事件：

| Responses stream event | 内部事件 |
|---|---|
| `response.output_text.delta` | `text_delta` |
| `response.reasoning_summary_text.delta` | `thinking_delta` |
| `response.function_call_arguments.delta` | `tool_call_delta` |
| `response.completed` | `done` |

所以 Agent 可以一边接收文本增量，一边保留最终 `AssistantMessage`，不需要把 streaming 和非 streaming 写成两套循环。

> 通俗解释：`SSE` 是一种“服务器持续往客户端吐数据”的通信方式。`delta` 是“一小块增量”的意思，所以 `text_delta` 就是“新吐出来的一小段文字”。非流式像“一次性给你整封邮件”，流式像“一个字一个字发微信”。


---


## Tool System：让错误也进入循环

工具注册表很简单：

```ts
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

执行器也保持了最小：

```ts
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

这里有一个小但关键的设计：工具不存在、参数错误、执行抛错，都不会直接中断 Agent。它们会变成一条 `role: "tool"` 且 `isError: true` 的消息，被写回 history。

这就是第一篇里说的原则：**Failures as First-Class Citizens。**

对模型来说，错误不是外部异常，而是一条 observation。模型可以基于它修正参数、换工具、或者告诉用户失败原因。

> 通俗解释：`Map` 在这里就是一个“名字 → 工具”的字典。`register` 是登记工具，`get` 是查找工具。`schema` 是工具参数的填写规则，`validateArguments` 就是检查模型交上来的参数有没有按规则填。`AbortSignal` 则是“如果用户中途取消，就发一个停止信号”。

#### `ToolRegistry` 逐行拆解

```ts
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

逐行拆解：

1. `export class ToolRegistry {`：定义一个公开的“工具注册表”类，专门用来管理有哪些工具。
2. `private readonly tools = new Map<string, AgentTool>();`：内部维护一张“名字 → 工具”的字典。`private` 表示这张表只能由注册表自己操作；`readonly` 表示这张表的引用不会在创建后换掉；`Map<string, AgentTool>` 表示键是工具名，值是工具对象。
3. `register(tool: AgentTool): void`：定义“登记工具”的方法，接收一个符合 `AgentTool` 形状的工具。
4. `if (this.tools.has(tool.name))`：先检查这个名字有没有已经登记过。
5. `throw new Error(...)`：如果名字重复，就主动报错，防止两个工具抢同一个名字。
6. `this.tools.set(tool.name, tool);`：如果名字不重复，就把工具放进字典，键是工具名，值是工具本身。
7. `get(name: string): AgentTool | undefined`：定义“查工具”的方法。给一个名字，返回对应工具；找不到就返回 `undefined`。
8. `return this.tools.get(name);`：直接从字典里查。
9. `toLlmToolSpecs(): LlmToolSpec[]`：定义“生成给模型看的工具说明书”的方法。它不把完整工具对象交给模型，只把模型需要的三个字段抽出来：`name`、`description`、`parameters`。
10. `return this.list().map(...)`：把工具列表逐个转换，生成一份只包含“模型需要知道的信息”的说明书数组。

> 通俗解释：`ToolRegistry` 像“员工花名册”。登记时检查有没有重名，查询时按名字找员工；给模型看的不是员工全部档案，而是精简版“岗位说明书”。

#### `ToolExecutor` 逐行拆解

```ts
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

逐行拆解：

1. `constructor(private readonly registry: ToolRegistry) {}`：构造执行器时，把工具注册表传进来并保存好。执行器需要靠注册表查工具。
2. `async execute(toolCall: ToolCall, signal?: AbortSignal): Promise<ToolResultMessage>`：定义“执行一次工具调用”的方法。`toolCall` 是模型发出的“我要用这个工具”的请求；`signal` 是可选取消信号。
3. `const tool = this.registry.get(toolCall.name);`：按工具名去注册表里查一下，看这个工具是否存在。
4. `if (!tool)`：如果查不到，说明模型点了一个不存在的工具。
5. `return toToolResultMessage(...)`：不抛异常让整个程序崩溃，而是生成一条 `Tool not found` 的错误结果消息，标记 `isError: true`，然后返回。
6. `try { ... }`：尝试执行下面的正常流程；如果中途出错，会被 `catch` 接住。
7. `validateArguments(tool.parameters, toolCall.arguments);`：先检查模型提交的参数是否符合工具规定的 `schema`，不符合就直接失败。
8. `const result = await tool.execute(toolCall.arguments, ...);`：真正调用工具自己定义的 `execute` 方法，等待它返回结果。
9. `return toToolResultMessage(toolCall, result);`：把真实执行结果包装成一条 `role: "tool"` 消息，返回给 Agent Loop。
10. `catch (error)`：如果工具执行过程中抛出了错误，不中断 Agent。
11. `return toToolResultMessage(...)`：把错误信息也包装成工具结果消息，并标记 `isError: true`。

> 通俗解释：`ToolExecutor` 像“派单员”。模型说要用某个工具，派单员先查这个工具在不在；在的话先核对表格有没有填对，再让工具去干；不管干成还是干砸，都要把结果写成一封正式的“结果报告”交回给 Agent，而不是让整个公司停工。


---


## 示例工具

当前内置了两个教学工具：`calculator` 和 `get_weather`。

`calculator` 的定义是：

```ts
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

这个工具写得很简单，主要是为了能用就行，重点是跑通工具调用链路：

```text
tool schema -> model tool call -> tool execution -> tool result message -> next model request
```

> 通俗解释：`schema` 告诉模型“你只能提交一个叫 `expression` 的文本参数，里面只能放数字、括号和加减乘除等符号”。模型只要提交符合这个表单的请求，宿主程序就会真正计算，然后把数字结果作为 observation 还给模型。


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

> 通俗解释：`reasoning` 是模型“先想后说”的思考过程；`reasoning effort` 是“思考用力程度”。`npm run demo` 只是启动这个演示程序的一条命令。你不需要记命令，只需要记住：模型没有直接背答案，而是先调用计算器，再根据真实结果回答。


---


## 我们从现有项目学到了什么？

这一版虽然叫“最小 Agent Loop”，但它不是最原始的 while loop。它在几个地方提前保留了扩展点。


### 1. 流式和非流式共用同一个 loop

```ts
if (!isStreamingLlmClient(this.llm)) {
  return this.llm.complete(request);
}

for await (const event of this.llm.stream(request)) {
  // thinking_delta / text_delta / tool_call_delta / done
}
```

streaming 只是 LLM Client 的增强能力。Agent Loop 仍然只等待一个最终 `AssistantMessage` 来决定是否执行工具。

> 通俗解释：流式只是“显示方式更顺滑”，Agent 做决策时依然等模型给出完整答复，不会因为界面一直在刷新就改变循环逻辑。

这段代码逐行看：

```ts
if (!isStreamingLlmClient(this.llm)) {
  return this.llm.complete(request);
}

for await (const event of this.llm.stream(request)) {
  // thinking_delta / text_delta / tool_call_delta / done
}
```

1. `isStreamingLlmClient(this.llm)`：检查当前这个模型客户端有没有“流式能力”。`!` 表示“没有”。
2. `return this.llm.complete(request);`：如果模型客户端不支持流式，就走非流式路径：把请求发过去，等完整答案回来。
3. `for await (const event of this.llm.stream(request))`：如果支持流式，就走流式路径：模型每吐一小段，就收到一个事件。
4. 注释里的四种事件：`thinking_delta` 是思考片段，`text_delta` 是正文片段，`tool_call_delta` 是工具调用参数片段，`done` 是全部结束。

> 通俗解释：这段代码像“检查餐厅有没有上菜传送带”。没有传送带，就等整桌菜一起端上来；有传送带，就一道一道接。不管哪种方式，最后都能吃上饭，Agent 的循环逻辑不用变。


### 2. 工具可以并行执行，但历史顺序稳定

`executeToolCalls` 支持两种策略：

```ts
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

如果模型一次请求多个互不依赖的工具，未来可以并发执行。但 `Promise.all` 的结果顺序和输入数组一致，所以写回 history 的顺序仍然稳定。Codex 和 Pi 的实现中都有这一部分：**性能可以并行，模型看到的上下文不能乱。**

> 通俗解释：并行执行像“同时点两份外卖”；但端上桌时必须按你下单的顺序摆好，否则模型会以为第二份才是第一份。上下文顺序一旦乱了，模型的推理就可能跟着乱。

把“并行执行和顺序回填”这句话拆开：

- **并行执行**：多个工具可以同时开始运行。比如模型一次要求调用“查天气”和“查日历”，这两个工具互不依赖，宿主程序就让它们同时跑，节省时间。
- **顺序回填**：不管这些工具谁先跑完，写回历史时都按照模型最初发出工具调用的顺序来，而不是按完成顺序来。
- **为什么要分开**：模型看到的历史必须稳定。如果模型先请求了 A 再请求了 B，那模型下一轮看到的也应该先是 A 的结果、再是 B 的结果。如果 B 更快跑完就先写 B，模型会以为顺序反了，推理就可能乱。

代码也可以拆开看：

```ts
const mustRunSequentially =
  this.toolExecution === "sequential" ||
  toolCalls.some((toolCall) => this.tools.get(toolCall.name)?.executionMode === "sequential");
```

1. `this.toolExecution === "sequential"`：如果任务级默认策略是“全部顺序执行”，那么这一批工具必须排队。
2. `toolCalls.some(...)`：检查这次请求的每一个工具，看有没有任何一个声明自己是 `sequential`。
3. `some` 的意思是“只要有一个满足就算满足”。所以只要全局是顺序，或者任何一个工具要求顺序，`mustRunSequentially` 就是真，这一批都走顺序执行。

```ts
const results = await Promise.all(
  toolCalls.map(async (toolCall) => this.executor.execute(toolCall, signal))
);
```

4. `toolCalls.map(...)`：把每个工具调用都变成一个“去执行它”的任务。
5. `Promise.all(...)`：让这些任务同时开始，然后等全部完成。
6. `Promise.all` 的一个重要性质是：结果数组的顺序和输入数组的顺序一致，不会因为谁先完成而乱序。这正是“并行执行，但顺序回填”的工程实现。

> 通俗解释：`Promise.all` 像“同时发快递，但按你填写的清单顺序编号”。每个快递员回来的时间可能不同，但最后汇总时依然按清单编号排列，模型看到的顺序不会乱。


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

这让模型有机会“读到失败”，而不是让宿主程序直接抛异常结束。

在真实 Agent 中，这个细节非常重要。因为工具失败太常见了：文件不存在、命令退出码非零、网络请求 429、参数 schema 不匹配、权限不足。失败如果不进入上下文，模型就没有自我修正的机会。

> 通俗解释：把错误也写成一条普通消息，相当于让模型看到“刚才这步失败了，原因是这个”。模型可以换一种写法、换一个工具，或者直接告诉用户失败原因。这个设计叫做“失败是第一等公民”。


### 4. 事件系统先行

当前 Agent 支持两种事件消费方式：

```ts
new Agent({
  onEvent(event) {
    // log, UI, SSE, WebSocket...
  }
});
```

也支持：

```ts
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

这让最小实现天然可以接 CLI、Web UI、HTTP SSE 或调试日志。后续加可观测性时，不需要再把 Agent Loop 拆开重写。

> 通俗解释：事件系统就像提前装好了“广播插座”。以后你想把 Agent 接到命令行、网页、手机界面或日志系统，只要插上对应的“收音机”就行，不用改 Agent 本身。

这两段事件代码逐行看：

```ts
new Agent({
  onEvent(event) {
    // log, UI, SSE, WebSocket...
  }
});
```

1. `new Agent({ ... })`：创建一个 Agent 实例，并在创建时把配置传进去。
2. `onEvent(event) { ... }`：给 Agent 注册一个“每当有事件发生时就会被调用”的函数。`event` 就是当前发生的事件。
3. 注释里的 `log, UI, SSE, WebSocket...` 表示：在这个函数里，你可以把事件写到日志、推给网页界面、转成 SSE 发送给浏览器，或者通过 WebSocket 推给客户端。

```ts
for await (const event of agent.runEvents(input)) {
  // async iterable event stream
}
```

4. `agent.runEvents(input)`：让 Agent 开始运行，并返回一个事件流。
5. `for await (... of ...)`：程序不需要一次性拿到全部事件，而是每收到一个事件就处理一个。`await` 表示“来一个处理一个，没来就先等着”。
6. `const event`：当前这一条事件，例如 `turn_start`、`tool_start`、`tool_end`。

> 通俗解释：第一种方式是“把收音机号码留给广播站，广播站主动打电话给你”；第二种方式是“你打开收音机，广播来一段你听一段”。两种方式都能收到同一套节目。


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

这个配置最终由 `OpenAIResponsesClient` 映射到 Responses API 的 `reasoning` 参数。Agent Loop 不需要知道 provider 的字段细节，只负责把通用配置传下去。

> 通俗解释：“Reasoning 配置放在 LLM 边界”的意思是：Agent 只知道“这次任务思考用力一点还是轻一点”，具体这个要求怎么翻译成 OpenAI 的字段，由翻译层负责。

这里的“翻译层”和前面说的“转换层”也是同一个意思：`OpenAIResponsesClient` 把 Agent 的通用 `reasoning` 配置翻译成 OpenAI Responses API 认识的参数。Agent 不关心字段叫什么，只关心“我传了一个通用要求”。


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
- 同步项目：[Tritium0041/Singularity](https://github.com/Tritium0041/Singularity)
