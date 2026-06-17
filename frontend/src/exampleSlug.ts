// Small client-side wordlist sample purely for the homepage's illustrative
// rotating example slug (design spec 2.1). The real slug is generated server-side.
const ADJECTIVES = [
  "quiet", "brave", "cosmic", "golden", "nimble", "stellar", "swift", "vivid",
  "mellow", "lucky", "breezy", "jazzy", "amber", "snug", "zesty", "wise",
];
const NOUNS = [
  "otter", "tiger", "panda", "falcon", "nebula", "harbor", "willow", "comet",
  "lynx", "meadow", "raven", "fjord", "orchid", "summit", "heron", "quartz",
];

export function randomExampleSlug(): string {
  const a = ADJECTIVES[Math.floor(Math.random() * ADJECTIVES.length)];
  const n = NOUNS[Math.floor(Math.random() * NOUNS.length)];
  const num = String(Math.floor(Math.random() * 100)).padStart(2, "0");
  return `${a}-${n}-${num}`;
}
