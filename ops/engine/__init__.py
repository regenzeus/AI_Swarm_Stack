"""The AI Stack's engine (GEN-33, docs/AI-STACK.md §3, docs/AI-STACK-PLAN.md): Temporal under the stack's tasks.

  converter.py  what may enter a run's history: references only on a customer-class deployment, and the codec that
                encrypts every payload with the deployment's key (GEN-36)
  client.py     the connection: this deployment's namespace, the data converter, the namespace made when missing
  worker.py     the engine thread inside the host runner: one event loop, the workers of its task queues, and calls
                into it from the runner's other threads

The workflows (the graph runner) and the activities come with later work packages. Nothing here starts on import."""
