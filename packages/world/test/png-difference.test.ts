import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  comparePngs,
  decodePng,
  encodePng,
  type RgbaImage,
} from "../scripts/png-difference.ts";

function image(width: number, height: number, pixels: number[]): RgbaImage {
  return { width, height, pixels: Uint8Array.from(pixels) };
}

describe("font review pixel evidence", () => {
  test("reads the PNG bytes it writes without changing a pixel", () => {
    const source = image(2, 2, [
      19, 27, 42, 255,
      46, 74, 140, 255,
      249, 248, 243, 255,
      76, 86, 101, 128,
    ]);

    assert.deepEqual(decodePng(encodePng(source)), source);
  });

  test("locates every changed pixel and keeps identical pixels quiet", () => {
    const approved = image(3, 2, [
      10, 10, 10, 255, 20, 20, 20, 255, 30, 30, 30, 255,
      40, 40, 40, 255, 50, 50, 50, 255, 60, 60, 60, 255,
    ]);
    const candidate = image(3, 2, [
      10, 10, 10, 255, 25, 20, 20, 255, 30, 30, 30, 255,
      40, 40, 40, 255, 50, 50, 50, 255, 60, 60, 70, 255,
    ]);

    const result = comparePngs(encodePng(approved), encodePng(candidate));

    assert.deepEqual(result.metrics.bounds, { x: 1, y: 0, width: 2, height: 2 });
    assert.equal(result.metrics.changed_pixels, 2);
    assert.equal(result.metrics.total_pixels, 6);
    assert.equal(result.metrics.changed_fraction, 2 / 6);
    assert.equal(result.metrics.maximum_channel_delta, 10);
    assert.equal(result.metrics.mean_changed_channel_delta, 2.5);
    assert.deepEqual(decodePng(result.difference).width, 3);
  });

  test("records a byte-identical frame as an empty difference, not a fake box", () => {
    const frame = encodePng(image(1, 1, [249, 248, 243, 255]));
    const result = comparePngs(frame, frame);

    assert.equal(result.metrics.changed_pixels, 0);
    assert.equal(result.metrics.changed_fraction, 0);
    assert.equal(result.metrics.mean_changed_channel_delta, 0);
    assert.equal(result.metrics.bounds, null);
  });

  test("refuses to compare frames of different sizes", () => {
    const one = encodePng(image(1, 1, [0, 0, 0, 255]));
    const two = encodePng(image(2, 1, [0, 0, 0, 255, 0, 0, 0, 255]));

    assert.throws(() => comparePngs(one, two), /same dimensions/);
  });
});
