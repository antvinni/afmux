# Trigger evaluation

Unit tests show that `afm` works. They cannot show that an agent reaches for
it. This directory holds a small manual evaluation to answer three questions
per task:

1. On a should-trigger task, did the agent call `afm`?
2. Did it pipe the input in without reading it first?
3. On a should-not task, did it leave `afm` alone? Over-delegation is a
   failure, the same as a miss.

## Running it

It uses the paid agents and costs tokens, so it is run by hand, before a
release and after any change to the skill description, the SKILL.md body or
the standing rule.

    ./run.sh            # every installed harness
    ./run.sh claude     # one harness

Each task in `tasks.json` runs in a fresh fixture repo built by
`fixture/make-fixture.sh`, in two settings: the skill alone, and the skill
plus the standing rule written into `CLAUDE.md` and `AGENTS.md`. Transcripts
land in `out/<date>/`. The script prints a rough `afm_calls` count per
transcript; scoring is done by reading them.

The harness must have the afmux skill installed and `afm` on `PATH`, and the
sandbox must allow `afm` to reach the model (see the main README).

## Recording results

Add one row per harness and setting to `RESULTS.md`, with the score as
"tasks passed / tasks" and a note on what failed. A description change is
judged against the previous row.
