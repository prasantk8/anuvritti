/** Pure presentation decisions for This Year's Film. */

import type { FilmMaterial } from "@anuvritti/client";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
] as const;

export interface FilmPeriod {
  readonly named: string;
  readonly materials: readonly FilmMaterial[];
}

/** Group an already chronological evidence ledger; a month is the only divider. */
export function shelveFilm(materials: readonly FilmMaterial[]): readonly FilmPeriod[] {
  const periods: FilmPeriod[] = [];
  for (const material of materials) {
    const year = material.captured_at.slice(0, 4);
    const month = Number(material.captured_at.slice(5, 7));
    const named = `${MONTHS[month - 1] ?? MONTHS[0]} ${year}`;
    const previous = periods.at(-1);
    if (previous?.named === named) {
      periods[periods.length - 1] = {
        named,
        materials: [...previous.materials, material],
      };
    } else {
      periods.push({ named, materials: [material] });
    }
  }
  return periods;
}

export const MADE_OF = "This is what the film is made of.";
