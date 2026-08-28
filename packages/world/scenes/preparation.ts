/** Validate a text-free render requirement before this package is allowed to fetch fonts. */

import { FILM_FONTS, FILM_SCRIPTS } from "./fonts.ts";

interface PackageIdentity {
  readonly name: string;
  readonly version: string;
}

interface ApprovedRequirements {
  readonly scripts: readonly string[];
}

function object(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${name} is not an object`);
  }
  return value as Record<string, unknown>;
}

export function approveRenderRequirements(
  value: unknown,
  worldPackage: PackageIdentity
): ApprovedRequirements {
  const requirements = object(value, "render requirements");
  if (requirements.schema !== "anuvritti.render-requirements.v1") {
    throw new Error("render requirements use an unapproved schema");
  }
  const world = object(requirements.world, "render requirements world");
  if (world.package !== worldPackage.name || world.version !== worldPackage.version) {
    throw new Error(
      `render requirements name ${String(world.package)}@${String(world.version)}, ` +
        `but this checkout is ${worldPackage.name}@${worldPackage.version}`
    );
  }

  const approvedPackages = Object.fromEntries(
    [...FILM_FONTS]
      .sort((left, right) => left.package.localeCompare(right.package))
      .map((face) => [face.package, face.version])
  );
  const requestedPackages = object(world.font_packages, "render requirements font_packages");
  const canonical = (packages: Record<string, unknown>) =>
    JSON.stringify(Object.entries(packages).sort(([left], [right]) => left.localeCompare(right)));
  if (canonical(requestedPackages) !== canonical(approvedPackages)) {
    throw new Error("render requirements do not name the approved pinned font bundle exactly");
  }

  if (
    !Array.isArray(requirements.scripts) ||
    requirements.scripts.some((script) => typeof script !== "string")
  ) {
    throw new Error("render requirements scripts is not a list of names");
  }
  const scripts = requirements.scripts as string[];
  const approvedScripts = new Set<string>(FILM_SCRIPTS.map((script) => script.name));
  const unsupported = scripts.filter((script) => !approvedScripts.has(script));
  if (unsupported.length) {
    throw new Error(`render requirements ask for unapproved scripts: ${unsupported.join(", ")}`);
  }
  return { scripts };
}

export function assertInstalledFilmFontDigests(
  actual: Readonly<Record<string, string>>
): void {
  for (const face of FILM_FONTS) {
    const digest = actual[face.file];
    if (digest !== face.sha256) {
      throw new Error(
        `installed font bytes are not approved: ${face.file} ` +
          `(expected ${face.sha256}, found ${digest ?? "missing"})`
      );
    }
  }
}
