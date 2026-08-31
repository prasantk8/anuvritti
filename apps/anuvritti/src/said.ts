/**
 * Every sentence the app itself says.
 *
 * Family material and server-authored reasons remain data. Everything written by this
 * interface lives here so tone, names and assumptions can be reviewed without hunting
 * through screens. In particular, none of this copy guesses a pronoun or relationship.
 */

export const SAID = {
  today: {
    saved: "Saved.",
    toVault: "Say something out loud →",
    emptyArchive: "Nothing here yet. Share something to this app and it will be.",
    nothing: "Nothing today. That's normal.",
    answers: [
      { action: "maybe_later", said: "Maybe later" },
      { action: "lets_do_it", said: "Let's do it" },
      { action: "not_relevant_anymore", said: "Not anymore" },
    ],
    acknowledgement: {
      maybe_later: "Put away for a while.",
      lets_do_it: "Good. It's on the list.",
      not_relevant_anymore: "Gone. Won't come back.",
    },
  },
  pairing: {
    title: "Anuvritti",
    subtitle: "For the little things you don't want life to erase.",
    start: "Start our family",
    joinChoice: "Join with a code",
    familyLabel: "What shall we call your family?",
    familyPlaceholder: "Our family",
    ownerLabel: "And you?",
    ownerPlaceholder: "Your name",
    begin: "Begin",
    codeLabel: "The code on the other phone",
    codePlaceholder: "ABCD-1234",
    join: "Join",
    failure: {
      offline: "Can't reach home right now. It may be reachable in a moment.",
      timeout: "That took too long. The connection may be ready now.",
      pairing: "That code didn't work. Ask for a fresh one.",
      conflict: "This server already belongs to a family.",
      unknown: "Something went wrong at our end.",
    },
  },
  vault: {
    kept: "That's in this year's film.",
    waitingForSignal: "Still on your phone. It will go up when there's signal.",
    empty: "Nothing here yet. This is where your voice lives.",
    prompts: [
      "What was said today that you want to keep?",
      "What word came out wrong in a way you hope never changes?",
      "What happened today that you would tell someone you love?",
      "What made you both laugh?",
      "What feels different at the moment, in one sentence?",
      "What is worth knowing but hard to say out loud?",
      "What happened that you didn't expect?",
      "What is the most ordinary thing about today?",
    ],
  },
  voice: {
    holdHint: "Hold to record. Let go to keep it.",
    hold: "Hold to talk",
    microphone: "Anuvritti needs the microphone to keep your voice.",
    pause: "Pause",
    play: "Play",
    recording: "Recording.",
    saved: "Saved.",
    resting: "Hold to talk.",
    heard: "It sounded like",
    uncertain: "Maybe",
  },
  spark: {
    turnedOver: "Turned over. Why you saved this.",
    turnedBack: "Turned back. What you saved.",
    noWhy: "You didn't say why. That's fine.",
  },
  capture: {
    screenshot: "that screenshot",
    photo: "that photo",
  },
  child: {
    title: "Bedtime",
    goodnight: "Goodnight.",
    holdToExit: "Hold to exit",
    listen: "Listen",
    playing: "Playing...",
    parentExit: "Parent Exit",
    parentPasscode: "Parent Passcode",
    enterPin: "Enter PIN",
    incorrectPin: "Incorrect passcode",
    cancel: "Cancel",
    unlock: "Unlock",
  },
} as const;
