# PRODUCT.md

## Register

**product** — design serves the task. This is an authenticated internal tool:
data tables, filters, rule builders, audit logs. Nobody is here to admire it;
they are here to decide which bids to cut before today's spend runs out.

## What this is

PPC OS manages Amazon Advertising for a seller account. It syncs campaigns, ad
groups, keywords and search terms into Postgres, applies numeric threshold rules
to produce **suggestions**, and — only after a human approves each one — writes
bid changes and negative keywords back to Amazon.

Scale that shapes every screen: 268 campaigns, 1,386 ad groups, **222,384
targets**. Density is not a stylistic preference here, it is the requirement.

## Users

PPC managers, not engineers. Small team, one seller account, three marketplaces
(US, CA, MX — US holds essentially all of it).

**The scene:** a PPC manager in a Jakarta office, mid-afternoon, bright ambient
light, third hour of scanning ACOS across hundreds of campaigns, deciding what to
cut. Bright room, long session, dense numerals. That forces light mode and a high
-legibility ink ramp; it rules out the low-contrast gray-on-gray that reads as
"designed" for ten minutes and becomes unusable for three hours.

**Their jobs, in the order they do them:**
1. Is the data current? (Sync Monitor, the header's marketplace selector)
2. What is costing money and not returning? (Campaign Manager, Keywords, Search Terms)
3. What does the app suggest I do, and do I agree? (Suggestions)
4. Automate the judgement I keep repeating (Rules, Dayparting)
5. What changed, and can I undo it? (Logs)

Step 3 is the product. Everything else feeds it.

## Personality

**Calm, dense, precise.** Chosen against Linear's discipline: hierarchy from
spacing and weight rather than boxes and rules; one accent; numbers aligned so
the eye can compare a column without reading it.

The interface should be boring in the way a well-made instrument is boring. When
a screen is interesting, something has gone wrong.

## Anti-references

- **Amazon Seller Central.** Familiar to the team and the weakest thing they use.
  Do not inherit its density-without-hierarchy, its orange, or its habit of
  three competing calls to action per panel.
- **Emoji as iconography.** The current build has 48 of them, 15 in the sidebar
  alone. They do not scale, do not align on the baseline, render differently per
  OS, and make a tool that moves real advertising money look like a hobby app.
- **Marketing-dashboard theatre.** Gradient hero metrics, cards nested in cards,
  celebratory colour on numbers that are merely large.
- **Warm near-white body backgrounds** (cream / sand / paper). Currently the
  saturated AI default and wrong for a data surface besides.

## Design principles

1. **Say the number, then say what it means.** Never a metric without its unit
   and period. `$45.93` and `19.6% ACOS` beat a bare `45.93`.
2. **Status must survive being photocopied.** Never colour alone — every state
   carries a word. The team screenshots this app to each other on WhatsApp.
3. **Empty is a sentence, not a shrug.** An empty table says which marketplace
   has the data, or that the sync is still running. This project has already
   shipped screens where "no campaigns" meant "wrong marketplace selected".
4. **Destructive things look destructive; irreversible things ask.** Writes to
   Amazon, rule deletion, schedule activation.
5. **Density over comfort, legibility over density.** In that order, and the
   second wins when they conflict.

## Accessibility

WCAG 2.1 AA. Body text ≥4.5:1, large text ≥3:1, placeholders held to body
contrast rather than the muted default. Full keyboard operation with a visible
focus ring on every interactive element. `prefers-reduced-motion` honoured
throughout. Status conveyed by text as well as colour (principle 2 above), which
covers colour-vision deficiency without a separate mode.
