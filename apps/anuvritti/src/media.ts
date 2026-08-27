/**
 * Where a recording's bytes are, and the proof this phone may have them (TASK-713).
 *
 * Everything else in the app talks to the server through `@anuvritti/client`, which holds
 * the token in one place and attaches it in one place (`transport.ts`). The audio player
 * is the single exception in the whole product: `useAudioPlayer` is given a source and
 * fetches the bytes itself, natively, knowing nothing about this family or its token.
 *
 * Handed a bare URL it therefore asks anonymously and is answered `401`. The screen still
 * renders — a play button, a waveform, a duration — and plays silence. That is the worst
 * shape a failure can take here: a parent taps a recording of themselves, hears nothing,
 * and concludes the recording is gone.
 *
 * So the source is an object with headers on it, built here and nowhere else. Verified
 * against the installed expo-audio@57 typings rather than from memory:
 *
 *     AudioSource = string | number | null | { uri?, assetId?, headers?, name? }
 *
 * and `headers` is documented as "the HTTP headers to send along with the request for a
 * remote audio source". `null` is a legal `AudioSource`, which is why the unpaired answer
 * below is `null` rather than an unauthenticated URL: a player that cannot be let in should
 * not be pointed at the door.
 */

/** An `AudioSource` this app can actually be allowed to play. */
export interface MediaSource {
  readonly uri: string;
  readonly headers: Record<string, string>;
}

/**
 * The bytes of one piece of media, with this device's bearer token.
 *
 * `/v1` and the trailing-slash trim mirror `transport.ts`'s `buildUrl`, because this is the
 * same server and a second spelling of its address is a second thing to get wrong.
 */
export function mediaSource(
  baseUrl: string,
  mediaId: string,
  token: string | null
): MediaSource | null {
  if (!token) return null;
  const root = baseUrl.replace(/\/+$/, "");
  return {
    uri: `${root}/v1/media/${encodeURIComponent(mediaId)}`,
    headers: { Authorization: `Bearer ${token}` },
  };
}
