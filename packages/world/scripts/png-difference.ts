/** Dependency-free PNG comparison for the font migration review. */

import { deflateSync, inflateSync } from "node:zlib";

import { palette } from "../src/tokens.ts";

export interface RgbaImage {
  readonly width: number;
  readonly height: number;
  readonly pixels: Uint8Array;
}

export interface PixelBounds {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface DifferenceMetrics {
  readonly total_pixels: number;
  readonly changed_pixels: number;
  readonly changed_fraction: number;
  readonly maximum_channel_delta: number;
  readonly mean_changed_channel_delta: number;
  readonly bounds: PixelBounds | null;
}

const SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

function paeth(left: number, above: number, upperLeft: number): number {
  const estimate = left + above - upperLeft;
  const leftDistance = Math.abs(estimate - left);
  const aboveDistance = Math.abs(estimate - above);
  const upperLeftDistance = Math.abs(estimate - upperLeft);
  if (leftDistance <= aboveDistance && leftDistance <= upperLeftDistance) return left;
  return aboveDistance <= upperLeftDistance ? above : upperLeft;
}

export function decodePng(bytes: Uint8Array): RgbaImage {
  const png = Buffer.from(bytes);
  if (png.length < SIGNATURE.length || !png.subarray(0, 8).equals(SIGNATURE)) {
    throw new Error("font review frame is not a PNG");
  }
  let position = 8;
  let width = 0;
  let height = 0;
  let channels = 0;
  const compressed: Buffer[] = [];
  while (position + 12 <= png.length) {
    const length = png.readUInt32BE(position);
    const type = png.toString("ascii", position + 4, position + 8);
    const start = position + 8;
    const end = start + length;
    if (end + 4 > png.length) throw new Error("font review PNG is truncated");
    if (type === "IHDR") {
      width = png.readUInt32BE(start);
      height = png.readUInt32BE(start + 4);
      const bitDepth = png[start + 8];
      const colourType = png[start + 9];
      const interlace = png[start + 12];
      if (bitDepth !== 8 || ![2, 6].includes(colourType!) || interlace !== 0) {
        throw new Error("font review PNG must be non-interlaced 8-bit RGB or RGBA");
      }
      channels = colourType === 6 ? 4 : 3;
    } else if (type === "IDAT") {
      compressed.push(png.subarray(start, end));
    } else if (type === "IEND") {
      break;
    }
    position = end + 4;
  }
  if (!width || !height || !channels || compressed.length === 0) {
    throw new Error("font review PNG is missing image data");
  }
  const packed = inflateSync(Buffer.concat(compressed));
  const stride = width * channels;
  if (packed.length !== height * (stride + 1)) {
    throw new Error("font review PNG has an unexpected data length");
  }
  const raw = Buffer.alloc(height * stride);
  for (let y = 0; y < height; y += 1) {
    const source = y * (stride + 1);
    const target = y * stride;
    const filter = packed[source];
    if (filter! > 4) throw new Error(`font review PNG uses unknown filter ${filter}`);
    for (let x = 0; x < stride; x += 1) {
      const value = packed[source + 1 + x]!;
      const left = x >= channels ? raw[target + x - channels]! : 0;
      const above = y > 0 ? raw[target + x - stride]! : 0;
      const upperLeft = y > 0 && x >= channels ? raw[target + x - stride - channels]! : 0;
      const reconstructed =
        filter === 0
          ? value
          : filter === 1
            ? value + left
            : filter === 2
              ? value + above
              : filter === 3
                ? value + Math.floor((left + above) / 2)
                : value + paeth(left, above, upperLeft);
      raw[target + x] = reconstructed & 0xff;
    }
  }
  const pixels = new Uint8Array(width * height * 4);
  for (let pixel = 0; pixel < width * height; pixel += 1) {
    const input = pixel * channels;
    const output = pixel * 4;
    pixels[output] = raw[input]!;
    pixels[output + 1] = raw[input + 1]!;
    pixels[output + 2] = raw[input + 2]!;
    pixels[output + 3] = channels === 4 ? raw[input + 3]! : 255;
  }
  return { width, height, pixels };
}

let crcTable: Uint32Array | undefined;

function crc32(bytes: Uint8Array): number {
  crcTable ??= Uint32Array.from({ length: 256 }, (_, value) => {
    let current = value;
    for (let bit = 0; bit < 8; bit += 1) {
      current = (current & 1) === 1 ? 0xedb88320 ^ (current >>> 1) : current >>> 1;
    }
    return current >>> 0;
  });
  let crc = 0xffffffff;
  for (const byte of bytes) crc = crcTable[(crc ^ byte) & 0xff]! ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type: string, data: Uint8Array): Buffer {
  const name = Buffer.from(type, "ascii");
  const body = Buffer.from(data);
  const result = Buffer.alloc(body.length + 12);
  result.writeUInt32BE(body.length, 0);
  name.copy(result, 4);
  body.copy(result, 8);
  result.writeUInt32BE(crc32(Buffer.concat([name, body])), body.length + 8);
  return result;
}

export function encodePng(image: RgbaImage): Buffer {
  if (image.width < 1 || image.height < 1 || image.pixels.length !== image.width * image.height * 4) {
    throw new Error("RGBA image dimensions do not match its pixels");
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(image.width, 0);
  header.writeUInt32BE(image.height, 4);
  header[8] = 8;
  header[9] = 6;
  const stride = image.width * 4;
  const scanlines = Buffer.alloc(image.height * (stride + 1));
  for (let y = 0; y < image.height; y += 1) {
    const row = y * (stride + 1);
    scanlines[row] = 0;
    Buffer.from(image.pixels.subarray(y * stride, (y + 1) * stride)).copy(scanlines, row + 1);
  }
  return Buffer.concat([
    SIGNATURE,
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(scanlines, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

export function magnifyPng(
  bytes: Uint8Array,
  bounds: PixelBounds,
  options: { readonly padding?: number; readonly scale?: number } = {}
): Buffer {
  const source = decodePng(bytes);
  if (
    bounds.x < 0 ||
    bounds.y < 0 ||
    bounds.width < 1 ||
    bounds.height < 1 ||
    bounds.x + bounds.width > source.width ||
    bounds.y + bounds.height > source.height
  ) {
    throw new Error("font review detail bounds must be inside the frame");
  }
  const padding = options.padding ?? 12;
  const scale = options.scale ?? 4;
  if (!Number.isInteger(padding) || padding < 0 || !Number.isInteger(scale) || scale < 2) {
    throw new Error("font review detail padding and scale must be non-negative integers with scale at least 2");
  }
  const left = Math.max(0, bounds.x - padding);
  const top = Math.max(0, bounds.y - padding);
  const right = Math.min(source.width, bounds.x + bounds.width + padding);
  const bottom = Math.min(source.height, bounds.y + bounds.height + padding);
  const cropWidth = right - left;
  const cropHeight = bottom - top;
  const width = cropWidth * scale;
  const height = cropHeight * scale;
  const pixels = new Uint8Array(width * height * 4);
  for (let y = 0; y < height; y += 1) {
    const sourceY = top + Math.floor(y / scale);
    for (let x = 0; x < width; x += 1) {
      const sourceX = left + Math.floor(x / scale);
      const sourceOffset = (sourceY * source.width + sourceX) * 4;
      pixels.set(source.pixels.subarray(sourceOffset, sourceOffset + 4), (y * width + x) * 4);
    }
  }
  return encodePng({ width, height, pixels });
}

function rgb(hex: string): readonly [number, number, number] {
  return [1, 3, 5].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16)) as unknown as readonly [
    number,
    number,
    number,
  ];
}

function paintBounds(pixels: Uint8Array, width: number, bounds: PixelBounds, colour: readonly number[]): void {
  const right = bounds.x + bounds.width - 1;
  const bottom = bounds.y + bounds.height - 1;
  for (let y = bounds.y; y <= bottom; y += 1) {
    for (let x = bounds.x; x <= right; x += 1) {
      const onEdge = x < bounds.x + 2 || x > right - 2 || y < bounds.y + 2 || y > bottom - 2;
      if (!onEdge) continue;
      const offset = (y * width + x) * 4;
      pixels.set(colour, offset);
      pixels[offset + 3] = 255;
    }
  }
}

export function comparePngs(approvedBytes: Uint8Array, candidateBytes: Uint8Array): {
  readonly difference: Buffer;
  readonly metrics: DifferenceMetrics;
} {
  const approved = decodePng(approvedBytes);
  const candidate = decodePng(candidateBytes);
  if (approved.width !== candidate.width || approved.height !== candidate.height) {
    throw new Error("approved and candidate frames must have the same dimensions");
  }
  const ground = rgb(palette("light").ground!);
  const mark = rgb(palette("light").indigo!);
  const difference = new Uint8Array(approved.pixels.length);
  let changedPixels = 0;
  let deltaSum = 0;
  let maximumDelta = 0;
  let minX = approved.width;
  let minY = approved.height;
  let maxX = -1;
  let maxY = -1;
  for (let pixel = 0; pixel < approved.width * approved.height; pixel += 1) {
    const offset = pixel * 4;
    let pixelDelta = 0;
    let alphaChanged = false;
    for (let channel = 0; channel < 3; channel += 1) {
      const delta = Math.abs(approved.pixels[offset + channel]! - candidate.pixels[offset + channel]!);
      pixelDelta = Math.max(pixelDelta, delta);
      deltaSum += delta;
      maximumDelta = Math.max(maximumDelta, delta);
    }
    alphaChanged = approved.pixels[offset + 3] !== candidate.pixels[offset + 3];
    const changed = pixelDelta > 0 || alphaChanged;
    if (changed) {
      changedPixels += 1;
      const x = pixel % approved.width;
      const y = Math.floor(pixel / approved.width);
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
    const strength = changed ? Math.max(0.38, pixelDelta / 255) : 0;
    const luminance =
      approved.pixels[offset]! * 0.2126 +
      approved.pixels[offset + 1]! * 0.7152 +
      approved.pixels[offset + 2]! * 0.0722;
    for (let channel = 0; channel < 3; channel += 1) {
      const quietContext = ground[channel]! * 0.88 + luminance * 0.12;
      difference[offset + channel] = Math.round(
        quietContext * (1 - strength) + mark[channel]! * strength
      );
    }
    difference[offset + 3] = 255;
  }
  const bounds =
    changedPixels === 0
      ? null
      : { x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 };
  if (bounds) paintBounds(difference, approved.width, bounds, mark);
  return {
    difference: encodePng({ width: approved.width, height: approved.height, pixels: difference }),
    metrics: {
      total_pixels: approved.width * approved.height,
      changed_pixels: changedPixels,
      changed_fraction: changedPixels / (approved.width * approved.height),
      maximum_channel_delta: maximumDelta,
      mean_changed_channel_delta: changedPixels === 0 ? 0 : deltaSum / (changedPixels * 3),
      bounds,
    },
  };
}
