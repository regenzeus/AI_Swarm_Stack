'use strict';
// WFL-06: the stack's own blocks on n8n's canvas (docs/N8N-MIGRATION.md §3.3). One node sends a step to Mission
// Control's step service (WFL-05) and waits, as n8n's Wait node does, until the runner posts the answer to this
// execution's resume URL; the answer is the node's output. Its kind makes it one block of the palette: an agent, a
// coding change, a crew job, a plan task, a question for the owner, a message, a memory search or note, a command at
// a place, or a whole plan. The Agent, Crew job, Place and Repository pickers read the stack's lists live
// (GET /catalog). Plain JavaScript: n8n loads it from N8N_CUSTOM_EXTENSIONS, nothing is built or fetched.
const STEPS = 'http://mission-control:8099/steps';
const CATALOG = 'http://mission-control:8099/catalog';
const WAIT_INDEFINITELY = new Date('3000-01-01T00:00:00.000Z');   // n8n's own "until resumed" (n8n-workflow)

const show = (...kinds) => ({ show: { kind: kinds } });

// One of the stack's lists as a picker's options: the full name, the id it sends, what it is for.
async function pick(fns, list) {
  const got = await fns.helpers.httpRequest({ method: 'GET', url: CATALOG, json: true });
  if (!got || !got.ok) throw new Error(`the stack's lists are not there: ${(got && got.error) || 'no answer'}`);
  return (got[list] || []).map((x) => ({
    name: x.name && x.name !== x.id ? `${x.name} (${x.id})` : x.id,
    value: x.id,
    description: x.purpose || (x.commands ? `Approved commands: ${x.commands.join(', ') || 'none yet'}` : undefined),
  }));
}

// An answer that is not "done" (failed, refused, cancelled) ends the run as an error, so n8n's history shows it in red.
// n8n resumes a waiting node by passing the webhook's data through it (it disables the node for the resume); a resume
// error on the waiting entry makes the node fail there instead, as n8n does when a sub-workflow it waited for failed.
// The answer stays the node's input, and its whole text is the error's description.
function failOnResume(ctx, answer) {
  const entry = ctx.runExecutionData && ctx.runExecutionData.executionData && ctx.runExecutionData.executionData.nodeExecutionStack[0];
  if (!entry) return;   // not a resume (n8n changed): the answer goes on as output, its status in it, never stuck waiting
  entry.node.disabled = false;
  entry.metadata = { ...(entry.metadata || {}), resumeError: {
    name: 'NodeOperationError',
    message: `The step ${answer.status || 'gave no status'}: ${answer.error || 'no reason given'}`,
    description: JSON.stringify(answer, null, 2),
  } };
}

// A JSON parameter: n8n gives the text, or the value when it comes from an expression.
const json = (v, d) => (typeof v === 'string' ? (v.trim() ? JSON.parse(v) : d) : v == null ? d : v);

class AistackStep {
  constructor() {
    this.description = {
      displayName: 'AI Stack step',
      name: 'aistackStep',
      icon: 'fa:robot',
      group: ['transform'],
      version: 1,
      subtitle: '={{ {agent: "Agent: " + $parameter["agent"], build: "Coding change in " + $parameter["repo"], crew: "Crew job: " + $parameter["job"], task: "Plan task #" + $parameter["task"], ask: "Ask the owner", notify: "Notify the owner", recall: "Recall: " + $parameter["query"], remember: "Remember a " + $parameter["note"], command: $parameter["command"] + " at " + $parameter["place"], plan: "Run a plan"}[$parameter["kind"]] }}',
      description: "A step of the stack's own work, sent to the stack and waited for: an agent, a coding change, a crew job, a plan task, a question for the owner, a message, memory, a command or a plan",
      defaults: { name: 'AI Stack step', color: '#6d5dfc' },
      inputs: ['main'],
      outputs: ['main'],
      webhooks: [{ name: 'default', httpMethod: 'POST', responseMode: 'onReceived', path: '', restartWebhook: true }],
      properties: [
        { displayName: 'Kind', name: 'kind', type: 'options', default: 'agent', noDataExpression: true,
          options: [
            { name: 'Agent step', value: 'agent', description: 'An agent of the stack does one piece of work' },
            { name: 'Coding change', value: 'build', description: 'The coder works in the sandbox on a repository: a branch or pull request, checks and your review included' },
            { name: 'Crew job', value: 'crew', description: 'A housekeeping job, as Run now starts it' },
            { name: 'Plan task', value: 'task', description: 'One run of a plan task (a briefing, a price watch)' },
            { name: 'Ask the owner', value: 'ask', description: 'A question in Needs you; the tap is the answer' },
            { name: 'Notify the owner', value: 'notify', description: "A message through the stack's notifications (Telegram, the app), quiet hours respected" },
            { name: 'Recall', value: 'recall', description: "Search the stack's memory; the hits are the answer" },
            { name: 'Remember', value: 'remember', description: 'A lesson, fact, failure or skill for memory; it enters only after the memory gate checks it' },
            { name: 'Run command', value: 'command', description: 'A command at a place (WSL, the WSL host, Windows), only once you approved it there' },
            { name: 'Run a plan', value: 'plan', description: 'The steps of a plan as waves of agent steps; every step\'s output is the answer' },
          ] },
        { displayName: 'Agent', name: 'agent', type: 'options', default: 'scout', displayOptions: show('agent', 'remember'),
          typeOptions: { loadOptionsMethod: 'getAgents' },
          description: 'The agent that does the step (for a note: whose note it is; a lesson goes to its role)' },
        { displayName: 'Repository', name: 'repo', type: 'options', default: '', displayOptions: show('build', 'remember'),
          typeOptions: { loadOptionsMethod: 'getRepos' },
          description: 'The repository the coder changes (for a note: the repository a failure belongs to)' },
        { displayName: 'Brief', name: 'brief', type: 'string', default: '', typeOptions: { rows: 5 }, displayOptions: show('agent', 'build'),
          description: 'What is to be done and what counts as done' },
        { displayName: 'Crew job', name: 'job', type: 'options', default: '', displayOptions: show('crew'),
          typeOptions: { loadOptionsMethod: 'getCrewJobs' } },
        { displayName: 'Plan task', name: 'task', type: 'number', default: 0, displayOptions: show('task'),
          description: 'The plan task by number' },
        { displayName: 'Question', name: 'question', type: 'string', default: '', displayOptions: show('ask') },
        { displayName: 'Why', name: 'why', type: 'string', default: '', displayOptions: show('ask'),
          description: 'One line the owner reads under the question' },
        { displayName: 'Answers', name: 'answers', type: 'string', default: 'Yes, No', displayOptions: show('ask'),
          description: 'Up to four, separated by commas; each is a button in Needs you' },
        { displayName: 'Message', name: 'message', type: 'string', default: '', typeOptions: { rows: 3 }, displayOptions: show('notify') },
        { displayName: 'Search for', name: 'query', type: 'string', default: '', displayOptions: show('recall') },
        { displayName: 'Where', name: 'scope', type: 'string', default: '', displayOptions: show('recall'),
          description: 'Empty for everything; or world, code, code:<repository>, howto, agents, or a collection' },
        { displayName: 'Note', name: 'note', type: 'options', default: 'fact', displayOptions: show('remember'),
          options: [
            { name: 'Lesson', value: 'lesson', description: 'How to do a kind of job better' },
            { name: 'Fact', value: 'fact', description: 'About the world' },
            { name: 'Failure', value: 'failure', description: 'What broke in a repository and why' },
            { name: 'Skill', value: 'skill', description: 'A procedure worth writing down' },
          ] },
        { displayName: 'Text', name: 'text', type: 'string', default: '', typeOptions: { rows: 3 }, displayOptions: show('remember'),
          description: 'One or two sentences' },
        { displayName: 'Evidence', name: 'evidence', type: 'string', default: '', displayOptions: show('remember'),
          description: 'Where it comes from: a file, page, address, commit, build or run' },
        { displayName: 'Place', name: 'place', type: 'options', default: 'wsl', displayOptions: show('command'),
          typeOptions: { loadOptionsMethod: 'getPlaces' } },
        { displayName: 'Command', name: 'command', type: 'string', default: '', displayOptions: show('command'),
          description: "The command's kind, as its pack names it (pack.kind); it runs only once you approved it at that place" },
        { displayName: 'Values', name: 'values', type: 'json', default: '{}', displayOptions: show('command'),
          description: "The command's parameters and their values" },
        { displayName: 'Steps', name: 'steps', type: 'json', displayOptions: show('plan'),
          default: '[\n  {"agent": "scout", "title": "Research", "brief": "Find ...", "after": []},\n  {"agent": "desk", "title": "Write", "brief": "Write ...", "after": [1]}\n]',
          description: 'Each step: an agent, its brief, a title, and the numbers of the steps it waits for' },
        { displayName: 'Title', name: 'title', type: 'string', default: '',
          description: "How Home's feed names this step" },
      ],
    };
    this.methods = {
      loadOptions: {
        async getAgents() { return pick(this, 'agents'); },
        async getCrewJobs() { return pick(this, 'crew'); },
        async getPlaces() { return pick(this, 'places'); },
        async getRepos() { return pick(this, 'repos'); },
      },
    };
  }

  async execute() {
    const p = (n, d) => this.getNodeParameter(n, 0, d);
    const kind = p('kind');
    const body = {
      kind,
      title: p('title', '') || undefined,
      workflow: this.getWorkflow().id,
      execution: this.getExecutionId(),
      resume_url: this.evaluateExpression('{{ $execution.resumeUrl }}', 0),
    };
    if (kind === 'agent') Object.assign(body, { agent: p('agent'), brief: p('brief') });
    if (kind === 'build') Object.assign(body, { repo: p('repo'), brief: p('brief') });
    if (kind === 'crew') body.job = p('job');
    if (kind === 'task') body.task = Number(p('task'));
    if (kind === 'notify') body.message = p('message');
    if (kind === 'ask') Object.assign(body, { question: p('question'), why: p('why', ''),
      answers: String(p('answers', 'Yes, No')).split(',').map((s) => s.trim()).filter(Boolean) });
    if (kind === 'recall') Object.assign(body, { query: p('query'), scope: p('scope', '') });
    if (kind === 'remember') Object.assign(body, { note: p('note'), text: p('text'), evidence: p('evidence', ''),
      agent: p('agent', '') || undefined, repo: p('repo', '') || undefined });
    if (kind === 'command') Object.assign(body, { place: p('place'), command: p('command'), values: json(p('values', '{}'), {}) });
    if (kind === 'plan') body.steps = json(p('steps', '[]'), []);
    const got = await this.helpers.httpRequest({ method: 'POST', url: STEPS, body, json: true });
    if (!got || !got.ok) throw new Error(`the step service refused the step: ${(got && got.error) || 'no answer'}`);
    await this.putExecutionToWait(WAIT_INDEFINITELY);
    return [this.getInputData()];
  }

  async webhook() {
    const answer = this.getRequestObject().body || {};
    if (answer.status !== 'done') failOnResume(this, answer);
    return { workflowData: [[{ json: answer }]] };
  }
}

module.exports = { AistackStep };
