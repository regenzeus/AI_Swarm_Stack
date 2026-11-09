// The stack's blocks as Workflow Builder node types (docs/AI-STACK.md §5): one palette item per block of the graph model
// (ops/engine/graph.py BLOCKS), each with the form its fields need. The forms are JSON Schema and JsonForms UI schemas,
// drawn by the SDK; the field names are the template's own, so toSpec() in main.jsx copies them across unchanged.
import { NodeType, getScope } from "@workflowbuilder/sdk";

const s = getScope;
const text = (scope, label, placeholder) => ({ type: "Text", scope: s(`properties.${scope}`), label, ...(placeholder ? { placeholder } : {}) });
const area = (scope, label, placeholder) => ({ type: "TextArea", scope: s(`properties.${scope}`), label, minRows: 4, ...(placeholder ? { placeholder } : {}) });
const pick = (scope, label) => ({ type: "Select", scope: s(`properties.${scope}`), label });
const group = (label, elements) => ({ type: "Accordion", label, elements });
const str = { type: "string" };
const opts = (list) => ({ type: "string", options: list.map((o) => ({ label: o.name || o.id, value: o.id })) });

const TRACKER_CALLS = ["comment", "summary", "attach", "link", "transition", "label"];

// What every block has: its title and why it is there, a fan-out, and a loop back for a block that checks.
const common = { label: str, description: str, each: str, loopMax: str };
const flowFields = group("Flow", [
  text("each", "Once per item of", "an earlier block's answer, e.g. spec.items"),
  text("loopMax", "Rounds back, at most", "when an arrow goes back from this block: 1 to 4"),
]);
const head = (what) => [text("label", "Title"), area("description", "Why", what)];

export function blocks({ agents = [], roles = [] }) {
  const agentList = agents.length ? agents : [{ id: "analyst", name: "analyst" }];
  const roleOpt = roles.length ? opts(roles) : str;
  const roleCtl = roles.length ? pick("role", "Who decides") : text("role", "Who decides", "a role, e.g. spec-approver");
  return [
    {
      type: "start", label: "Start", description: "What starts a run: by hand, on a schedule, when a tracker item arrives, or on an event", icon: "Lightning",
      templateType: NodeType.Node, isStartNode: true,
      schema: { type: "object", required: ["label", "kind"], properties: { label: str, description: str,
        kind: { type: "string", options: [["hand", "By hand"], ["schedule", "On a schedule"], ["item", "When a tracker item arrives"], ["event", "On an event"]].map(([value, label]) => ({ value, label })) },
        trigger: str } },
      defaultPropertiesData: { label: "Start", description: "", kind: "hand", trigger: "" },
      uischema: { type: "VerticalLayout", elements: [group("Start", [...head("what a run is for"), pick("kind", "Starts"),
        text("trigger", "When or what", "a schedule (daily 07:00, weekly mon 08:00), the tracker's query, or the event")])] },
    },
    {
      type: "agent", label: "Agent", description: "An agent does a step with its own card: its harness, model and tools", icon: "Robot",
      templateType: NodeType.Node,
      schema: { type: "object", required: ["label", "agent"], properties: { ...common, agent: opts(agentList), brief: str } },
      defaultPropertiesData: { label: "Agent step", description: "", agent: agentList[0].id, brief: "", each: "", loopMax: "" },
      uischema: { type: "VerticalLayout", elements: [group("Step", [...head("what this step is for"), pick("agent", "Agent"), area("brief", "What to do", "the instructions; the agent's card brings its tools, model and limits")]), flowFields] },
    },
    {
      type: "branch", label: "Decision", description: "An agent answers a question, and the run goes down the branch it names", icon: "ArrowsSplit",
      templateType: NodeType.DecisionNode,
      schema: { type: "object", required: ["label", "agent"], properties: { ...common, agent: opts(agentList), brief: str,
        decisionBranches: { type: "array", items: { type: "object", properties: { id: str, sourceHandle: str, label: str,
          conditions: { type: "array", items: { type: "object", properties: { x: str, comparisonOperator: str, y: str, logicalOperator: str } } } } } } } },
      defaultPropertiesData: { label: "Decide", description: "", agent: agentList[0].id, brief: "", each: "", loopMax: "", decisionBranches: [] },
      uischema: { type: "VerticalLayout", elements: [group("Decision", [...head("what is decided here"), pick("agent", "Who decides"), area("brief", "The question", "e.g. Is the change ready to deliver? Answer with one branch's name")]),
        group("Branches", [{ type: "DecisionBranches", scope: s("properties.decisionBranches") }]), flowFields] },
    },
    {
      type: "command", label: "Command", description: "A job of a known kind runs, without a model", icon: "TerminalWindow",
      templateType: NodeType.Node,
      schema: { type: "object", required: ["label", "kind"], properties: { ...common, kind: str,
        place: { type: "string", options: [["wsl", "The stack (wsl)"], ["wsl-host", "The WSL host, as the tools' owner"], ["windows", "Windows"]].map(([value, label]) => ({ value, label })) } } },
      defaultPropertiesData: { label: "Command", description: "", kind: "", place: "wsl", each: "", loopMax: "" },
      uischema: { type: "VerticalLayout", elements: [group("Command", [...head("what it checks or makes"), text("kind", "Job", "its kind, e.g. toy.reproduce"), pick("place", "Runs at")]), flowFields] },
    },
    {
      type: "change", label: "Change", description: "A coder changes a repository on its own branch", icon: "GitBranch",
      templateType: NodeType.Node,
      schema: { type: "object", required: ["label"], properties: { ...common, agent: opts(agentList), brief: str } },
      defaultPropertiesData: { label: "Change", description: "", agent: (agentList.find((a) => a.id === "builder") || agentList[0]).id, brief: "", each: "", loopMax: "" },
      uischema: { type: "VerticalLayout", elements: [group("Change", [...head("what changes"), pick("agent", "Coder"), area("brief", "What to change")]), flowFields] },
    },
    {
      type: "gate", label: "Approval", description: "A person decides before the run goes on", icon: "Stamp",
      templateType: NodeType.Node,
      schema: { type: "object", required: ["label", "role"], properties: { ...common, role: roleOpt } },
      defaultPropertiesData: { label: "Approve", description: "", role: roles[0]?.id || "", each: "", loopMax: "" },
      uischema: { type: "VerticalLayout", elements: [group("Approval", [...head("what is approved"), roleCtl])] },
    },
    {
      type: "wait", label: "Wait", description: "The run waits for an answer from outside, with reminders, and gives up after a while", icon: "Hourglass",
      templateType: NodeType.Node,
      schema: { type: "object", required: ["label", "for", "key", "timeout", "then"], properties: { ...common, for: str, key: str, remind: str, timeout: str, then: str } },
      defaultPropertiesData: { label: "Wait", description: "", for: "", key: "item", remind: "2d", timeout: "7d", then: "", each: "", loopMax: "" },
      uischema: { type: "VerticalLayout", elements: [group("Wait", [...head("what it waits for"), text("for", "Waits for", "who answers, e.g. reporter"),
        text("key", "Answer to", "e.g. item"), text("remind", "Remind after", "e.g. 2d, 5d"), text("timeout", "Gives up after", "e.g. 7d"), text("then", "Then tells", "who hears of it")])] },
    },
    {
      type: "notify", label: "Notify", description: "Tells someone something; the run does not wait", icon: "BellRinging",
      templateType: NodeType.Node,
      schema: { type: "object", required: ["label", "role", "brief"], properties: { ...common, role: roleOpt, brief: str } },
      defaultPropertiesData: { label: "Tell me", description: "", role: roles[0]?.id || "owner", brief: "", each: "", loopMax: "" },
      uischema: { type: "VerticalLayout", elements: [group("Notify", [...head("why they hear it"), roles.length ? pick("role", "Who hears it") : text("role", "Who hears it", "a role, e.g. owner"),
        area("brief", "What they hear")])] },
    },
    {
      type: "end", label: "End", description: "What a run delivers, and whether reaching it counts as done or as stopped", icon: "FlagCheckered",
      templateType: NodeType.Node,
      schema: { type: "object", required: ["label", "kind"], properties: { label: str, description: str,
        kind: { type: "string", options: [{ value: "done", label: "Done" }, { value: "stopped", label: "Stopped (not done)" }] } } },
      defaultPropertiesData: { label: "Done", description: "", kind: "done" },
      uischema: { type: "VerticalLayout", elements: [group("End", [...head("what the run delivered"), pick("kind", "Counts as")])] },
    },
    {
      type: "tracker", label: "Tracker", description: "A comment, summary, link or move on the issue tracker", icon: "Kanban",
      templateType: NodeType.Node,
      schema: { type: "object", required: ["label", "kind"], properties: { ...common, kind: { type: "string", options: TRACKER_CALLS.map((k) => ({ label: k, value: k })) }, role: roleOpt } },
      defaultPropertiesData: { label: "Tracker", description: "", kind: "comment", role: "", each: "", loopMax: "" },
      uischema: { type: "VerticalLayout", elements: [group("Tracker", [...head("what is posted"), pick("kind", "Does"), roleCtl])] },
    },
  ];
}

export const BLOCK_ICONS = { start: "Lightning", end: "FlagCheckered", notify: "BellRinging", agent: "Robot", branch: "ArrowsSplit", command: "TerminalWindow", change: "GitBranch", gate: "Stamp", wait: "Hourglass", tracker: "Kanban" };
export const BLOCK_TEMPLATE = { branch: NodeType.DecisionNode };
