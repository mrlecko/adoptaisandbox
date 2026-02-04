# APHORISMS.md

72 pragmatic aphorisms for agentic engineering, sandboxed execution, and production-minded delivery.

## Requirements and Scope

1. Ambiguity is just delayed debugging.
2. A requirement that cannot be tested is a wish.
3. Freeze one path to success before you fan out options.
4. Scope creep starts where acceptance criteria stop.
5. A demo spec should optimize for trust, not feature count.
6. If two docs disagree, neither is documentation.
7. Non-negotiables belong in contracts, not in prose.
8. The first command a reviewer runs defines your product.
9. Requirements are good when they remove choices at the right time.

## Architecture and Boundaries

10. Good architecture is mostly disciplined refusal.
11. Let the model plan; never let it execute unsandboxed.
12. Boundaries are where safety becomes real.
13. Every shortcut across a layer becomes a future outage.
14. The cleanest abstraction is the one that survives bad inputs.
15. Separate orchestration from execution and both become simpler.
16. Pluggable backends are easy; preserving invariants across them is hard.
17. If a component can fail, give it a graceful failure path.
18. Architecture quality is measured by how little panic a change causes.

## Agent Behavior and Tooling

19. An agent without tools is usually a narrator.
20. Tool calling is behavior; prompts are only hints.
21. The safest tool is the one with the narrowest input contract.
22. If the agent can answer without evidence, it eventually will.
23. Force the model to earn confidence through execution results.
24. Structured output is not bureaucracy; it is anti-chaos.
25. Retries without new constraints are just repetition at scale.
26. Stateful chat without persistent memory is roleplay.
27. A good agent explains results, not intentions.

## Security and Sandboxing

28. Assume generated code is hostile until proven harmless.
29. Sandbox policy should fail closed, not fail politely.
30. No network is a feature, not a limitation.
31. Read-only mounts are cheaper than incident response.
32. Timeouts are security controls wearing performance clothing.
33. Output limits prevent exfiltration disguised as helpfulness.
34. Validation is the final authority, not the model.
35. Every denied query teaches you what to log next.
36. Security posture is a product decision repeated in code.

## Testing and Evidence

37. A passing test suite is proof; a passing demo is luck.
38. Start with one deterministic smoke test and defend it fiercely.
39. Regressions hide where “obvious” behavior is untested.
40. Tactical tests beat heroic full-suite reruns during iteration.
41. If CI and local disagree, developers will trust neither.
42. Evidence beats explanation in every technical review.
43. Logs are test artifacts when they answer specific questions.
44. Flaky tests are architecture feedback in disguise.
45. The best test names read like failure postmortems avoided.

## Operations and Deployment

46. Deployment is architecture under pressure.
47. A green build that cannot be reproduced is a false summit.
48. Health checks should test readiness, not optimism.
49. One-command setup is kindness operationalized.
50. Helm values are code paths; treat them like code paths.
51. Local-first reliability buys credibility for remote claims.
52. If image tags are ambiguous, your incidents will be too.
53. Observe first, optimize second, automate third.
54. Every environment difference is a bug with a calendar reminder.

## Collaboration and Documentation

55. The best handoff is a runnable command, not a paragraph.
56. Source of truth is singular or it is fiction.
57. Status docs should report facts, not aspirations.
58. Changelogs are for future teammates, including future you.
59. Good docs reduce meetings by pre-answering failure modes.
60. Orientation guides are architecture for human memory.
61. Documentation debt compounds faster than code debt.
62. If a new agent cannot onboard in minutes, your system is opaque.
63. Clarity is the highest form of velocity.

## Strategy and Craft

64. Build the smallest reliable system, then scale ambition.
65. Optional features are mandatory complexity.
66. Most “hard” problems are sequencing problems.
67. Pick defaults that survive stress, not demos.
68. Design for rollback before you design for scale.
69. Reliability is just disciplined humility in production form.
70. The shortest path is rarely the fastest path twice.
71. Progress is when the same bug cannot happen the same way again.
72. Engineering maturity is measured by what no longer surprises you.

