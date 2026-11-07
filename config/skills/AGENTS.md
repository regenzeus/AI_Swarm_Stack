# config/skills: methods for the code roles

Third-party text, pinned: `config/skills.yaml` names the source, its commit, the licence and the hash of each file. `ops/skills.py`
hands a role its skills only when a run asks for them, and a file that changed since its review reaches no agent.

Adding or updating a skill: read the whole text first, as text from anywhere is data until a person has read it. Then copy it here,
write its hash into `config/skills.yaml`, and run the replay exam with and without it. It stays only where the exam improves (CHG-18).
