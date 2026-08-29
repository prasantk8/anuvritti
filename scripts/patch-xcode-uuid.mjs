import { readFileSync, writeFileSync } from "node:fs";

const xcodePath = new URL("../node_modules/xcode/package.json", import.meta.url);
const lockPath = new URL("../package-lock.json", import.meta.url);
const installLockPath = new URL("../node_modules/.package-lock.json", import.meta.url);
const expectedIntegrity =
  "sha512-kCz5k7J7XbJtjABOvkc5lJmkiDh8VhjVCGNiqdKCscmVpdVUpEAyXv1xmCLkQJ5dsHqx3IPO4XW+NTDhU/fatA==";
const reviewed = {
  version: "3.0.1",
  dependency: "^7.0.3",
  replacement: "11.1.1",
  license: "Apache-2.0",
};

const xcode = JSON.parse(readFileSync(xcodePath, "utf8"));
const lock = JSON.parse(readFileSync(lockPath, "utf8"));
const installLock = JSON.parse(readFileSync(installLockPath, "utf8"));
const locked = lock.packages?.["node_modules/xcode"];
const installedLock = installLock.packages?.["node_modules/xcode"];

if (
  xcode.version !== reviewed.version ||
  xcode.license !== reviewed.license ||
  locked?.version !== reviewed.version ||
  locked?.integrity !== expectedIntegrity ||
  installedLock?.version !== reviewed.version ||
  installedLock?.integrity !== expectedIntegrity
) {
  throw new Error(
    "xcode provenance changed; remove or re-review the TASK-741 compatibility patch",
  );
}

const installedDeclaration = xcode.dependencies?.uuid;
const lockedDeclaration = locked.dependencies?.uuid;
const installLockDeclaration = installedLock.dependencies?.uuid;
if (![reviewed.dependency, reviewed.replacement].includes(installedDeclaration)) {
  throw new Error(
    `xcode now declares uuid ${installedDeclaration}; remove or re-review the TASK-741 compatibility patch`,
  );
}
if (![reviewed.dependency, reviewed.replacement].includes(lockedDeclaration)) {
  throw new Error(
    `the xcode lock now declares uuid ${lockedDeclaration}; remove or re-review the TASK-741 compatibility patch`,
  );
}
if (![reviewed.dependency, reviewed.replacement].includes(installLockDeclaration)) {
  throw new Error(
    `the installed xcode lock declares uuid ${installLockDeclaration}; remove or re-review the TASK-741 compatibility patch`,
  );
}

xcode.dependencies.uuid = reviewed.replacement;
locked.dependencies.uuid = reviewed.replacement;
installedLock.dependencies.uuid = reviewed.replacement;
writeFileSync(xcodePath, `${JSON.stringify(xcode, null, 2)}\n`, "utf8");
writeFileSync(lockPath, `${JSON.stringify(lock, null, 2)}\n`, "utf8");
writeFileSync(installLockPath, `${JSON.stringify(installLock, null, 2)}\n`, "utf8");
console.log(
  installedDeclaration === reviewed.replacement &&
    lockedDeclaration === reviewed.replacement &&
    installLockDeclaration === reviewed.replacement
    ? "TASK-741 xcode UUID compatibility patch already applied"
    : "TASK-741 patched xcode@3.0.1 metadata for uuid@11.1.1",
);
