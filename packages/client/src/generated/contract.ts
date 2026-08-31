// Generated from docs/contracts/openapi.yaml by packages/client/codegen/generate.py.
// Do not edit. Run `make client` and commit the result; `make design` fails on drift.
//
// Erasable syntax only - Node strips these types rather than compiling them, so there are
// no enums, no namespaces and nothing else that would need a build step.

import type { CallOptions, RequestOptions, Result } from "../runtime/types.ts";

export type { CallOptions, RequestOptions, Result };

/**
 * An instant in time, as the server wrote it.
 *
 * Branded, and deliberately not a `Date`. TASK-507 says the interface never renders
 * elapsed time as a number, and the cheapest way for that to fail is for someone to
 * reach for `Date.now() - new Date(created_at)` under a deadline. This type does not
 * subtract. Use `saved` or `elapsed`, which arrive already worded.
 */
export type Instant = string & { readonly __instant: unique symbol };

/**
 * How long ago something was, in the words a parent would use.
 *
 * "8 months ago", never "247". Branded so it cannot be confused with an arbitrary
 * string, and so a search for what produces one finds every site at once.
 */
export type Elapsed = string & { readonly __elapsed: unique symbol };

export const API_VERSION = "0.3.0";

// ---------------------------------------------------------------- schemas
export interface ErrorEnvelope {
  readonly error: {
    readonly code: string;
    readonly message: string;
    readonly details?: Record<string, unknown>;
  };
}
/** All 10 intents available (TASK-816, PRD 13, PRD 50). */
export type IntentType = "DO" | "BUY" | "WATCH" | "READ" | "TEACH" | "REMEMBER" | "COOK" | "VISIT" | "TELL" | "LISTEN";
export const INTENT_TYPE_VALUES: readonly IntentType[] = ["DO", "BUY", "WATCH", "READ", "TEACH", "REMEMBER", "COOK", "VISIT", "TELL", "LISTEN"] as const;
export type SparkStatus = "CAPTURED" | "WAITING" | "RELEVANT" | "SUGGESTED" | "PLANNED" | "EXPERIENCED" | "REMEMBERED" | "ARCHIVED";
export const SPARK_STATUS_VALUES: readonly SparkStatus[] = ["CAPTURED", "WAITING", "RELEVANT", "SUGGESTED", "PLANNED", "EXPERIENCED", "REMEMBERED", "ARCHIVED"] as const;
export type SourceKind = "URL" | "TEXT" | "SCREENSHOT" | "PHOTO" | "VOICE";
export const SOURCE_KIND_VALUES: readonly SourceKind[] = ["URL", "TEXT", "SCREENSHOT", "PHOTO", "VOICE"] as const;
export type Visibility = "PRIVATE" | "FAMILY" | "CHILD_VISIBLE";
export const VISIBILITY_VALUES: readonly Visibility[] = ["PRIVATE", "FAMILY", "CHILD_VISIBLE"] as const;
/** PRD §13/§42 — every AI-derived field carries its provenance. */
export interface Attributed {
  readonly value: unknown;
  readonly source: "HUMAN" | "AI" | "DEFAULT";
  readonly confidence: number;
  readonly human_override: boolean;
}
export interface AgeRange {
  readonly min_years: number;
  readonly max_years: number;
}
/** A paired device as a parent deciding what to revoke would need to see it. No token, no fingerprint, no request count. `last_seen_at` is the only usage fact kept. */
export interface Device {
  readonly id: string;
  readonly display_name: string;
  readonly created_at: Instant;
  readonly last_seen_at: Instant | null;
  readonly revoked: boolean;
}
export type IssuedDevice = Device & {
  readonly token?: string;
};
/** The family, and the token for the device that just created it. */
export interface Bootstrap {
  readonly id: string;
  readonly name: string;
  readonly members: readonly Member[];
  readonly children: readonly Child[];
  readonly device: IssuedDevice;
}
export interface PairingCode {
  readonly code: string;
  readonly expires_in_seconds: number;
}
export interface ClaimPairing {
  readonly code: string;
  readonly device_name: string;
}
export interface Claimed {
  readonly device: IssuedDevice;
  readonly family: Family;
}
export interface CreateFamily {
  readonly name: string;
  readonly owner_display_name: string;
}
export interface Family {
  readonly id: string;
  readonly name: string;
  readonly members: readonly Member[];
  readonly children: readonly Child[];
}
export interface Member {
  readonly id: string;
  readonly display_name: string;
  readonly role: "PARENT" | "CO_PARENT" | "CHILD" | "GRANDPARENT";
}
export interface CreateChild {
  readonly display_name: string;
  readonly date_of_birth: string;
}
export interface Child {
  readonly id: string;
  readonly display_name: string;
  readonly date_of_birth: string;
  readonly age_years: number;
}
/** `family_id` and `owner_id` are optional and should be omitted: the token already says who this is. They are still *accepted*, and a value that disagrees with the token is a 403 rather than a silently redirected write, so a client with a stale id finds out rather than writing into the right family by luck. */
export interface CaptureSpark {
  readonly family_id?: string | null;
  readonly owner_id?: string | null;
  readonly subject_child_id?: string | null;
  readonly source: {
    readonly kind: SourceKind;
    readonly url?: string | null;
    readonly text?: string | null;
    readonly creator?: string | null;
    readonly title?: string | null;
    readonly media_id?: string | null;
  };
  readonly note?: string | null;
  readonly visibility?: Visibility;
}
export interface Spark {
  readonly id: string;
  readonly family_id: string;
  readonly owner_id: string;
  readonly subject_child_id?: string | null;
  readonly title: string;
  readonly note?: string | null;
  readonly source: {
    readonly kind?: SourceKind;
    readonly url?: string | null;
    readonly creator?: string | null;
    readonly title?: string | null;
    readonly media_id?: string | null;
  };
  readonly intent: Attributed;
  readonly age_range?: Attributed;
  readonly category: Attributed;
  readonly tags: readonly string[];
  readonly why?: {
    readonly text?: string | null;
    readonly voice_media_id?: string | null;
    readonly voice?: VoiceNote;
    readonly recorded_at?: Instant;
  };
  readonly status: SparkStatus;
  readonly visibility: Visibility;
  readonly saved: Elapsed;
  readonly created_at: Instant;
}
/** At least one of text / voice_media_id. Voice preferred (PRD §12). */
export interface RecordWhy {
  readonly text?: string | null;
  readonly voice_media_id?: string | null;
}
export interface OverrideField {
  readonly field: "intent" | "age_range" | "category";
  readonly value: unknown;
}
/** PRD §14/§48 F6. Contains no urgency, no counts, no streaks. `reason` is warm and factual; `actions` are exactly the three the PRD names. */
export interface Suggestion {
  readonly spark: Spark;
  readonly reason: string;
  readonly elapsed: Elapsed;
  readonly actions: readonly ("maybe_later" | "lets_do_it" | "not_relevant_anymore")[];
}
export interface SuggestionResponse {
  readonly response: "maybe_later" | "lets_do_it" | "not_relevant_anymore";
}
/** All fields optional — "nothing" is a valid answer (PRD §15). */
export interface MarkAsDone {
  readonly happened_on?: string | null;
  readonly reflection?: string | null;
  readonly photo_media_id?: string | null;
  readonly audio_media_id?: string | null;
}
export interface Moment {
  readonly id: string;
  readonly spark_id: string;
  readonly happened_on: string;
  readonly reflection?: string | null;
  readonly photo_media_id?: string | null;
  readonly audio_media_id?: string | null;
  readonly created_at: Instant;
}
export interface CaptureLittleThing {
  readonly family_id?: string | null;
  readonly author_id?: string | null;
  readonly subject_child_id?: string | null;
  readonly text?: string | null;
  readonly audio_media_id?: string | null;
}
/** PRD §17. `voice` comes before `text` on purpose: the recording is the artifact and the words are a lesser way of giving the same answer (TASK-602). */
export interface LittleThing {
  readonly id: string;
  readonly voice?: VoiceNote;
  readonly audio_media_id?: string | null;
  readonly text?: string | null;
  readonly created_at: Instant;
}
/** PRD §8.7. Words that stand in for a recording in a search box, and nowhere else. `source` is never `DEFAULT`: a transcript is either a machine's reading or a person's statement, and the object exists so a client cannot render the words without the provenance sitting beside them. */
export interface Transcript {
  readonly text: string;
  readonly source: "AI" | "HUMAN";
  readonly confidence: number;
  readonly engine: string;
  readonly made_at: Instant;
}
/** A recording that was kept (PRD §12, §17, §21). Identified by its media id, because the recording *is* the record — there is no shape here that can describe a transcript whose audio has gone. */
export interface VoiceNote {
  readonly media_id: string;
  readonly duration_seconds: number;
  readonly recorded_at: Instant;
  readonly transcript?: Transcript;
}
/** PRD §21. Deliberately has no count field of any kind. */
export interface Vault {
  readonly recordings: readonly VoiceNote[];
}
/** One real source for the annual film; exactly one payload is present. */
export interface FilmMaterial {
  readonly kind: "RECORDING" | "SPARK";
  readonly captured_at: Instant;
  readonly recording?: VoiceNote;
  readonly spark?: Spark;
}
/** The phone's truthful view of this year's film. Deliberately no scene count, duration, completion, percentage or target. */
export interface FilmCompilation {
  readonly child_name: string;
  readonly year: number;
  readonly materials: readonly FilmMaterial[];
  readonly rendered_media_id?: string | null;
}
export interface KeepVoiceNote {
  readonly family_id?: string | null;
  readonly author_id?: string | null;
  readonly media_id: string;
  readonly duration_seconds: number;
  readonly heard_text?: string | null;
  readonly heard_confidence?: number | null;
}
export interface CorrectTranscript {
  readonly text: string;
}
export interface CaptureRightNow {
  readonly family_id?: string | null;
  readonly child_id: string;
  readonly prompt?: string;
  readonly answer: string;
}
export interface RightNow {
  readonly id: string;
  readonly child_id: string;
  readonly prompt: string;
  readonly answer: string;
  readonly captured_at: Instant;
}
export interface Media {
  readonly id: string;
  readonly kind: string;
  readonly mime_type: string;
  readonly byte_size: number;
  readonly encrypted: boolean;
}
/** PRD §44 — export everything, in a form the family can actually read. */
export interface FamilyExport {
  readonly exported_at?: Instant;
  readonly family?: Family;
  readonly sparks?: readonly Spark[];
  readonly moments?: readonly Moment[];
  readonly little_things?: readonly LittleThing[];
  readonly right_now?: readonly RightNow[];
  readonly media_manifest?: readonly Media[];
}

// ------------------------------------------------------------- operations

/** What each operation is, so the transport is written once rather than per call. */
export const OPERATIONS = {
  bootstrapFamily: { method: "POST", path: "/families", pathParams: [], queryParams: [], hasBody: true, idempotent: false, open: true },
  openPairing: { method: "POST", path: "/pairing/codes", pathParams: [], queryParams: [], hasBody: false, idempotent: false, open: false },
  claimPairing: { method: "POST", path: "/pairing/claim", pathParams: [], queryParams: [], hasBody: true, idempotent: false, open: true },
  listDevices: { method: "GET", path: "/devices", pathParams: [], queryParams: [], hasBody: false, idempotent: false, open: false },
  revokeDevice: { method: "DELETE", path: "/devices/{device_id}", pathParams: ["device_id"], queryParams: [], hasBody: false, idempotent: false, open: false },
  addChild: { method: "POST", path: "/families/{family_id}/children", pathParams: ["family_id"], queryParams: [], hasBody: true, idempotent: false, open: false },
  captureSpark: { method: "POST", path: "/sparks", pathParams: [], queryParams: [], hasBody: true, idempotent: true, open: false },
  searchSparks: { method: "GET", path: "/sparks", pathParams: [], queryParams: ["q", "intent", "child_id", "age", "status", "limit"], hasBody: false, idempotent: false, open: false },
  getSpark: { method: "GET", path: "/sparks/{spark_id}", pathParams: ["spark_id"], queryParams: [], hasBody: false, idempotent: false, open: false },
  recordWhy: { method: "POST", path: "/sparks/{spark_id}/why", pathParams: ["spark_id"], queryParams: [], hasBody: true, idempotent: false, open: false },
  overrideField: { method: "POST", path: "/sparks/{spark_id}/override", pathParams: ["spark_id"], queryParams: [], hasBody: true, idempotent: false, open: false },
  markAsDone: { method: "POST", path: "/sparks/{spark_id}/done", pathParams: ["spark_id"], queryParams: [], hasBody: true, idempotent: true, open: false },
  worthBringingBack: { method: "GET", path: "/return/worth-bringing-back", pathParams: [], queryParams: ["child_id"], hasBody: false, idempotent: false, open: false },
  respondToSuggestion: { method: "POST", path: "/return/{spark_id}/respond", pathParams: ["spark_id"], queryParams: [], hasBody: true, idempotent: false, open: false },
  captureLittleThing: { method: "POST", path: "/little-things", pathParams: [], queryParams: [], hasBody: true, idempotent: true, open: false },
  todaysPrompt: { method: "GET", path: "/right-now", pathParams: [], queryParams: [], hasBody: false, idempotent: false, open: false },
  captureRightNow: { method: "POST", path: "/right-now", pathParams: [], queryParams: [], hasBody: true, idempotent: true, open: false },
  keepVoiceNote: { method: "POST", path: "/voice", pathParams: [], queryParams: [], hasBody: true, idempotent: true, open: false },
  listVoiceNotes: { method: "GET", path: "/voice", pathParams: [], queryParams: [], hasBody: false, idempotent: false, open: false },
  getVoiceNote: { method: "GET", path: "/voice/{media_id}", pathParams: ["media_id"], queryParams: [], hasBody: false, idempotent: false, open: false },
  correctTranscript: { method: "POST", path: "/voice/{media_id}/transcript", pathParams: ["media_id"], queryParams: [], hasBody: true, idempotent: false, open: false },
  compileFilm: { method: "POST", path: "/film/compile", pathParams: [], queryParams: [], hasBody: false, idempotent: false, open: false },
  uploadMedia: { method: "POST", path: "/media", pathParams: [], queryParams: [], hasBody: true, idempotent: false, open: false },
  downloadMedia: { method: "GET", path: "/media/{media_id}", pathParams: ["media_id"], queryParams: [], hasBody: false, idempotent: false, open: false },
  exportFamily: { method: "GET", path: "/families/{family_id}/export", pathParams: ["family_id"], queryParams: [], hasBody: false, idempotent: false, open: false },
  getFamily: { method: "GET", path: "/families/{family_id}", pathParams: ["family_id"], queryParams: [], hasBody: false, idempotent: false, open: false },
  deleteFamily: { method: "DELETE", path: "/families/{family_id}", pathParams: ["family_id"], queryParams: [], hasBody: false, idempotent: false, open: false },
} as const;

export type OperationName = keyof typeof OPERATIONS;

/** The generated surface. One method per documented operation, and no others. */
export interface Contract {
  /**
   * The founding device is paired by this act rather than by a second call: a window between "the family exists" and "the family is protected" is a window someone else can walk through. The returned token is shown exactly once.
   * On a production box this closes after the first family (409). Second families arrive in TASK-901 with real accounts.
   */
  bootstrapFamily(body: CreateFamily, options?: CallOptions): Promise<Result<Bootstrap>>;
  /** Eight Crockford characters, single use, ten minutes, attempt-limited. */
  openPairing(options?: CallOptions): Promise<Result<PairingCode>>;
  /** Wrong, malformed, expired, already-claimed and locked-out all answer identically with `PAIRING_FAILED`. Telling them apart tells a caller which codes exist. */
  claimPairing(body: ClaimPairing, options?: CallOptions): Promise<Result<Claimed>>;
  listDevices(options?: CallOptions): Promise<Result<readonly Device[]>>;
  revokeDevice(deviceId: string, options?: CallOptions): Promise<Result<Device>>;
  addChild(familyId: string, body: CreateChild, options?: CallOptions): Promise<Result<Child>>;
  /** Accepts url | text | screenshot | photo | voice. AI enrichment runs inline. */
  captureSpark(body: CaptureSpark, options?: RequestOptions): Promise<Result<Spark>>;
  searchSparks(query?: { readonly q?: string; readonly intent?: IntentType; readonly childId?: string; readonly age?: number; readonly status?: SparkStatus; readonly limit?: number; }, options?: CallOptions): Promise<Result<readonly Spark[]>>;
  getSpark(sparkId: string, options?: CallOptions): Promise<Result<Spark>>;
  recordWhy(sparkId: string, body: RecordWhy, options?: CallOptions): Promise<Result<Spark>>;
  overrideField(sparkId: string, body: OverrideField, options?: CallOptions): Promise<Result<Spark>>;
  /** Every attachment is optional. "Nothing" is a valid answer — no journaling burden. */
  markAsDone(sparkId: string, body: MarkAsDone, options?: RequestOptions): Promise<Result<Moment>>;
  /** Returns at most `max_suggestions_per_day` items. An empty list is normal and silent. Payload contains no urgency, no counters, no guilt (PRD §8.5, enforced by test). */
  worthBringingBack(query?: { readonly childId?: string; }, options?: CallOptions): Promise<Result<readonly Suggestion[]>>;
  respondToSuggestion(sparkId: string, body: SuggestionResponse, options?: CallOptions): Promise<Result<Spark>>;
  captureLittleThing(body: CaptureLittleThing, options?: RequestOptions): Promise<Result<LittleThing>>;
  todaysPrompt(options?: CallOptions): Promise<Result<{
  readonly prompt?: string;
}>>;
  captureRightNow(body: CaptureRightNow, options?: RequestOptions): Promise<Result<RightNow>>;
  /** The bytes are already at `POST /media`; this says how long they are and what, if anything, the handset's own recogniser made of them. There is no minimum duration and there never will be — PRD §24 says nothing is rejected for being unpolished, and a validator with a floor in it is that promise quietly undone. */
  keepVoiceNote(body: KeepVoiceNote, options?: RequestOptions): Promise<Result<VoiceNote>>;
  /** No total, no unheard count and no cursor. This is a shelf, and a shelf does not tell you how far behind you are (PRD §8.5). */
  listVoiceNotes(options?: CallOptions): Promise<Result<Vault>>;
  getVoiceNote(mediaId: string, options?: CallOptions): Promise<Result<VoiceNote>>;
  /** The only way to produce a `HUMAN` transcript. Permanent — no later run of a better model overrides it — and it never touches the audio. */
  correctTranscript(mediaId: string, body: CorrectTranscript, options?: CallOptions): Promise<Result<VoiceNote>>;
  /** Returns the evidence in capture order. `rendered_media_id` is null until the provenance-verified renderer has deposited an MP4 in the family archive; null is an honest not-yet, never a progress state. */
  compileFilm(options?: CallOptions): Promise<Result<FilmCompilation>>;
  uploadMedia(body: FormData, options?: CallOptions): Promise<Result<Media>>;
  /** Decrypted on the way out and never cached (`Cache-Control: private, no-store`). Media belonging to another family answers `MEDIA_NOT_FOUND` — the same answer an id that never existed gets, so the response cannot be used to discover a stranger's photograph is there. */
  downloadMedia(mediaId: string, options?: CallOptions): Promise<Result<Uint8Array>>;
  exportFamily(familyId: string, options?: CallOptions): Promise<Result<FamilyExport>>;
  getFamily(familyId: string, options?: CallOptions): Promise<Result<Family>>;
  deleteFamily(familyId: string, options?: CallOptions): Promise<Result<Record<string, unknown>>>;
}
