# KALI 2.0 — Architecture Walkthrough (for investors)

Companion to the L2 container diagram (`kali-2.0-containers.puml` /
`kali-2.0-render.html`). Read this while pointing at the boxes.

## In one sentence

KALI turns a spoken request from a non-technical person into a working, private AI
agent on their own machine — and lets them share it the way they share a video.

## The shift we are betting on

Every operating system today is static: the user adapts to fixed apps, menus, and
windows. KALI is generative: you say what you want, and the system builds it for you.
That is the direction the whole industry is moving. The difference is who we build it
for (people who can't code), where it runs (their own hardware), and how it spreads
(sharing, not ads).

## How to read the diagram

The white box is KALI, running on the user's machine. Blue boxes are the parts we own
and build. Grey boxes are outside services we can swap out. The whole picture is one
loop: **speak → generate → check → run → show → remember → share.** Follow the arrows
from the top.

## Walk the loop

**1. Voice Gateway — the way in.** The user talks. KALI wakes on "Hey Jarvis,"
transcribes the speech, and answers out loud. This runs on the user's own GPU; cloud
voice is only a backup. *Why it matters:* voice is the only interface a builder, a
doctor, or an office worker will actually use. It works today.

**2. Generative core — the part that builds.** It takes the request and writes the
agent: first as a safe description of what the agent should do, and only if needed as
real code. Before anything installs, it tests the agent itself. *Why it matters:* this
box is the "generative OS." The test step separates a demo from something a
non-technical person can trust — they can't read the code, so KALI checks it for them.

**3. Reasoner Router — the swappable brain.** Hard thinking goes to the best model
available: a cloud model today, a local one tomorrow. KALI is tied to no single
provider. *Why it matters:* models get cheaper and smaller every month. We treat the
model as a part we replace, not a moat we depend on. Whatever wins, KALI uses it.

**4. Capability Sandbox, Consent Broker, Capability Catalog — the trust layer.** Every
agent runs inside limits. When it wants the calendar, the files, or messages, KALI asks
the user in plain words: "Let this read your calendar?" The riskiest actions come only
from a reviewed catalog. *Why it matters:* as agents grow more capable, a hard boundary
is the only thing that prevents a disaster. This is what lets a non-technical person
grant real access without fear — and it is something a cloud assistant cannot match,
because there your data leaves your machine.

**5. UI Composer and Surface — what the user sees.** Today, a normal app: chat plus an
agent store. Next, the screen assembles itself around the task at hand. *Why it
matters:* the same path that ships a product today grows into the "Iron Man" interface
later, with no rebuild.

**6. Local memory and data — why it is yours.** Your agents, your history, your
preferences — all of it lives on your machine, not on our servers. *Why it matters:*
this is ownership, and it grows more valuable as agents do more for you. It is the
opposite of every cloud assistant.

**7. Share & Install — how it spreads.** A finished agent becomes a link or a short
video. A friend watches, taps install, and has it — then builds their own. *Why it
matters:* distribution lives inside the product. We grow when users show friends, not
when we buy ads. That loop is how a small team beats the giants.

## What is defensible, and what is not

- **The model (grey box) is a commodity.** We do not try to out-build OpenAI's model.
  We use whichever is best.
- **The edges are the moat (blue boxes):** the voice interface for non-technical
  people, the trust layer that keeps data on the machine, and the sharing loop. Those
  are the parts the giants cannot copy without giving up their cloud business.

## Why now

Models are commoditizing fast. As that happens, value moves off the model and onto the
edges — trust, distribution, and an interface ordinary people can use. KALI is built to
ride that curve. The three dials on the diagram (cloud → local, descriptions → code,
app → full shell) slide forward as AI improves, with no rewrite.

## What already runs (this is not a promise)

- **Works today:** voice in and out on a local GPU, the model router, local memory,
  the app.
- **In progress:** the generator, the trust layer, sharing.
- **Future:** the self-composing interface and a dedicated device.

The near-term product — speak, get an agent, share it — stands on parts that already
run.

## Questions an investor will ask

**"Won't OpenAI or Google just do this?"** They sell cloud and model access. Moving
your data and your agents onto your own machine works against that business. We use
their models; we do not fight them on models.

**"Why local? Isn't cloud easier?"** Privacy, ownership, and cost — and local gets
easier every month as models shrink. Cloud stays as a fallback, never a requirement.

**"How does it grow?"** Each agent is shareable as a link or a reel. Users bring users.
No ad budget required.

**"What if models stay cloud-only?"** The router already uses the cloud; nothing
breaks. Local is upside, not a dependency.

## The 30-second version

"Using an AI assistant today means typing to a chatbot in the cloud that forgets you
and owns your data. KALI flips that: you talk, and it builds you a personal assistant
that runs on your own machine, remembers you, and asks permission before it touches
anything. You make one by voice in three minutes and share it like a short video. We
don't compete with OpenAI on models — we use them. We win on who it is for, where it
runs, and how it spreads."

---

*Naming note: "Jarvis" and the Iron-Man reference are a working metaphor, pending an
IP review before public launch.*
