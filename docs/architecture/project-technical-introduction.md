# Video Workflow Service 技术介绍

## 1. 项目定位

`video_workflow_service` 是一个以工作流为中心的短视频生成系统。当前阶段重点是把视频生成过程拆成一组可控、可追踪、可插入人工审核的稳定节点；在工作流稳定之后，系统也预留了后续逐步引入更多 agent 特性的空间。

项目当前重点解决的是这几类问题：

- 如何把一个总体创意拆成多个连续子场景
- 如何让首帧、连续性、对白和镜头节奏真正参与场景生成
- 如何让用户在关键节点做人机协同，而不是在结果出来之后被动接受
- 如何把真实模型调用、项目状态、生成产物和提示词快照沉淀成可审计的系统状态

从产品边界看，它是一个 `workflow-first`、`provider-backed`、`HITL-capable` 的视频生产后端与前端一体项目。

## 2. 设计原则

当前架构围绕以下原则收敛：

- 不做 agent 编排，优先做确定性工作流
- 视频生成必须走真实 provider，不用 mock 跑主链路
- 节点职责解耦，但每个节点都可以拿到受控的全局纠偏上下文
- 首帧不是生成前的补丁参数，而是场景起点真值
- 用户一旦在 HITL 中修改并确认当前场景 prompt，系统不能再偷偷重写
- 最终给模型的 prompt 必须是某次生成的不可变快照，便于追踪和复盘

## 3. 总体架构

系统由一个 Python 后端和一个 React 前端组成，采用单仓库、静态前端产物由后端托管的方式运行。

```text
Browser (React + TypeScript + Vite)
        |
        v
HTTP API / Static Asset Server
        |
        v
Workflow Service Orchestrator
        |
        +--> LLM Runtime (Doubao Ark Chat)
        +--> Video Provider Adapter (Doubao / Seedance)
        +--> Image Generation Adapter (Doubao Seedream)
        +--> Media / FFmpeg Composition
        +--> Project Repository / Artifact Storage
```

### 3.1 后端分层

- `api`
  负责 HTTP 接口、状态查询、静态资源和产物文件分发。
- `application`
  负责项目创建、工作流编排、状态流转、HITL 审批和任务冻结。
- `domain`
  定义 `Project`、`Scene`、`SceneVideoJob`、`WorkflowRunJob` 等核心对象。
- `workflow`
  负责节点 contract、提示模板、上下文装配、节点执行逻辑。
- `llm`
  负责 Doubao LLM 调用与节点级模型路由。
- `providers`
  负责视频生成和图像生成 provider 适配。
- `storage`
  负责项目 JSON 持久化和 artifact 路径管理。
- `infrastructure`
  负责配置加载、路径、运行时设置。

### 3.2 前端结构

前端使用 `React + TypeScript + Vite`，但部署形态仍是静态产物，由 Python 服务托管。

前端的目标不是做复杂编辑器，而是承载当前阶段最关键的工作流交互：

- 创建项目
- 查看规划结果
- 设置或上传首帧
- 编辑当前场景视频提示词
- 逐场景生成与批准
- 合成最终视频

## 4. 核心工作流

当前主链路已经从“单次一键跑完”演进成“全局规划 + 场景级 HITL”的形态：

```text
scene1_first_frame_prepare
-> scene1_first_frame_analyze
-> prompt_optimize
-> story_plan
-> scene_plan
-> dialogue_allocate
-> scene_prompt_render
-> scene_video_generate
-> final_compose
```

各节点职责如下。

### 4.1 `scene1_first_frame_prepare`

为首场景准备 concrete first frame。

- `scene-01` 在任务开始前必须二选一：
  - `upload`
  - `auto_generate`
- `scene-02..N` 默认使用 `continuity`，也允许切到 `upload` 或 `auto_generate`

### 4.2 `scene1_first_frame_analyze`

对首场景已确定的首帧做图片理解，抽取起点视觉事实，例如：

- 主角是否已出镜
- 当前姿态与持物状态
- 构图与景别
- 环境与光线
- 连续性锚点

这一步的结果不是直接拼进最终 prompt，而是作为上游规划的纠偏上下文。

### 4.3 `prompt_optimize`

从用户原始需求中收敛全局创意意图、风格、对白素材和 planning notes。

### 4.4 `story_plan`

这是新增的全局叙事规划节点，用于回答：

- 总体故事线是什么
- 在当前总时长和 scene 数下，每个场景为什么存在
- 每个场景承担什么叙事职责
- 哪些 scene 适合对白，哪些 scene 应该静默
- 当前场景时长意味着多大的叙事容量

它的本质是“先全局，再子场景”。

### 4.5 `scene_plan`

在 `story_plan` 的基础上，把每个 scene 落到视觉和动作层：

- `narrative`
- `visual_goal`
- `continuity_notes`
- 时长内的动作和镜头目标

这里已经不再直接生成最终视频 prompt。

### 4.6 `dialogue_allocate`

把对白分配到不同 scene。

它不是机械拆句，而是结合：

- 总体叙事逻辑
- scene 角色
- scene 时长容量
- 节奏推进

决定每个场景：

- 是否说话
- 说多少
- 怎样说

### 4.7 `scene_prompt_render`

这是场景级最终提示词编译节点。

它的定位不是再做一次场景规划，而是把上游产物适配成视频模型能消费的场景视频提示词。它会综合：

- `scene_plan`
- `dialogue_allocate`
- 首帧或 continuity 事实
- 当前场景工作稿

然后输出系统建议稿。

### 4.8 `scene_video_generate`

冻结本次生成的场景 prompt，调用真实视频 provider 生成视频、尾帧和元数据。

### 4.9 `final_compose`

将所有已批准场景按顺序合成最终视频，并保留音频。

## 5. 首帧编排设计

首帧是当前系统的重要设计重点。

### 5.1 首帧不是后置参数

项目已经不再把首帧当成“视频生成前临时附加的参考图”，而是视为：

- `scene-01` 的起点真值
- 后续连续性的全局锚点
- 规划阶段可用的纠偏信息

### 5.2 首场景与后续场景的差异

- `scene-01`
  开始前必须选 `upload` 或 `auto_generate`
- `scene-02..N`
  默认使用前一场尾帧做 `continuity`
  但允许用户显式 override

### 5.3 图片理解的作用边界

图片理解的目标不是决定故事如何发展，而是告诉系统：

- 视频从什么视觉事实开始
- 后续 prompt 不能与这些事实冲突

例如：如果首帧里人物已经手持花束、位于室内药房、中近景出镜，那么下游 prompt 不应再写成“手伸进画面去桌上拿花”。

## 6. Prompt 与工件语义

为避免“一个字段承担多种语义”，当前系统已经把几个关键工件区分开。

### 6.1 `scene.narrative`

场景规划产物，表达这个 scene 在故事里的职责和视觉意图。

### 6.2 `scene.prompt`

当前场景的用户可编辑工作稿。

它面向 HITL，不等于最终一定发给模型的文本，但一旦用户确认并点击生成，这版就会被冻结用于本次生成。

### 6.3 `scene.rendered_prompt`

系统根据当前规划和上下文编译出的建议稿。

如果用户尚未手动介入，前端默认看到的就是这版。

### 6.4 `approved_prompt`

用户点击 `Generate Scene` 时冻结下来的 prompt。

在 HITL 语义下，这一版就是本次生成的权威输入，后端不会再偷偷改写。

### 6.5 `provider_prompt_snapshot`

某次实际调用模型时使用的不可变快照。

它用于：

- 复盘
- 审计
- 调试
- 对比不同生成尝试

### 6.6 `prompt_stale`

当首帧、连续性或上游约束发生变化时，系统只会标记当前 prompt 已过期，不会自动覆盖用户工作稿。

## 7. 轻量上下文装配

当前系统没有引入一个重型“全局上下文管理器”，而是采用轻量上下文装配方式。

设计目标是：

- 每个节点只拿到它真正需要的全局纠偏信息
- 不把所有上游字段一股脑灌进每个节点
- 保持职责解耦，但避免节点各自为政

目前主要通过以下组件完成：

- `context_types.py`
- `context_assembler.py`
- `node_context_policy.py`

这种设计避免了“共享一大坨上下文对象”的语义侵入问题。

## 8. Provider 与模型选型

当前项目优先使用 Doubao 体系，把视频、图像、LLM 尽量收在同一 provider 族中，降低配置复杂度。

### 8.1 视频生成

- Provider：Doubao / Seedance
- 默认模型：`doubao-seedance-1-5-pro-251215`

### 8.2 LLM 节点

- Provider：Doubao Ark Chat
- 默认模型：`doubao-seed-2-0-lite-260215`

节点级模型支持单独覆盖，例如：

- `VIDEO_WORKFLOW_LLM_PROMPT_OPTIMIZE_MODEL`
- `VIDEO_WORKFLOW_LLM_STORY_PLAN_MODEL`
- `VIDEO_WORKFLOW_LLM_SCENE_PLAN_MODEL`
- `VIDEO_WORKFLOW_LLM_DIALOGUE_ALLOCATE_MODEL`
- `VIDEO_WORKFLOW_LLM_FIRST_FRAME_ANALYZE_MODEL`
- `VIDEO_WORKFLOW_LLM_SCENE_PROMPT_RENDER_MODEL`

### 8.3 首帧自动生图

- 图像生成模型：`doubao-seedream-5-0-lite-260128`

## 9. 前端交互设计

前端已经从早期“平铺卡片 + 手动翻找下一步”演进成更贴近工作流的设计。

### 9.1 主布局

当前主界面采用：

- `scene timeline`
- `active scene workspace`
- `sticky next action`

这意味着系统会始终把“下一步该做什么”推到用户面前，而不是让用户自己在页面里翻找。

### 9.2 HITL 交互方式

用户看到的主流程是：

1. 创建项目
2. 查看分场景规划
3. 设置首帧
4. 编辑当前场景 `Scene Prompt`
5. 点击 `Generate Scene`
6. 审核并 `Approve Scene`
7. 系统自动聚焦下一个可操作场景
8. 所有场景批准后，主动作切换为 `Compose Final Video`

### 9.3 生成前 prompt 审批的处理方式

当前没有额外设计一个可见的 “Approve Prompt” 按钮。

交互语义是：

- 用户可直接编辑 `Scene Prompt`
- 点击 `Generate Scene` 就代表“按当前这版 prompt 生成”

这让交互更符合社区常见的视频生成产品心智。

### 9.4 长任务可视化

`Generate Scene` 后，前端不再只是把按钮变成 `Generating...`，而是展示：

- 场景级生成中面板
- 当前冻结的首帧预览
- 当前冻结的 prompt 摘要
- provider 渲染中的阶段占位

## 10. 运行与持久化

### 10.1 环境管理

- Python：`uv`
- Frontend：`npm`

### 10.2 数据落盘

当前主要运行数据落在：

- `runtime_data/projects/`
  项目状态快照
- `runtime_data/artifacts/`
  场景视频、尾帧、最终成片
- `runtime_data/logs/<project_id>/workflow_trace.jsonl`
  append-only 工作流轨迹

### 10.3 日志与追踪

系统会记录：

- 工作流阶段输出
- LLM 节点结果
- 生成任务元数据
- prompt snapshot
- HITL 交互痕迹

## 11. 当前实现边界

目前项目已经具备：

- 真实 provider 跑通的视频生成链路
- 基于 LLM 的全局规划、场景规划、对白分配、提示词编译
- 首帧上传 / 自动生成 / 连续性输入
- 场景级 HITL 审核
- 前端的工作流式交互

但它仍然处在“可运行、可演示、架构已成型”的阶段，距离更高强度使用还有一些后续方向：

- `scene_prompt_render` 进一步收窄成更纯粹的视频提示词编译器
- 更细的首帧多模态 grounding
- 更强的多场景叙事载荷均衡
- 从 polling 升级到 `SSE`
- 更稳定的进程外 worker 和任务执行边界

## 12. 总结

当前 `video_workflow_service` 的核心价值，不是“把多个模型拼起来”，而是把视频生产这件事拆成了一条清晰可控的工作流：

- 上游先做全局规划
- 中间做分场景设计和对白分配
- 下游结合首帧、连续性和用户输入生成可执行场景 prompt
- 在关键点插入 HITL
- 用真实 provider 交付结果

这使项目同时具备了三种能力：

- 能跑通真实视频生成
- 能追踪每一步为什么这样生成
- 能在用户需要时插手纠偏，而不是让系统完全黑盒运行
