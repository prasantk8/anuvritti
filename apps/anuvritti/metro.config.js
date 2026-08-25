// Metro, taught where the monorepo's own packages are.
//
// `@anuvritti/world` and `@anuvritti/client` have no build step - they are TypeScript that
// Node strips and Metro transpiles. That is only possible if Metro watches them as source
// rather than looking for a compiled `dist` in `node_modules`.

const { getDefaultConfig } = require("expo/metro-config");
const path = require("node:path");

const project = __dirname;
const workspace = path.resolve(project, "../..");

const config = getDefaultConfig(project);

config.watchFolders = [workspace];
config.resolver.nodeModulesPaths = [
  path.resolve(project, "node_modules"),
  path.resolve(workspace, "node_modules"),
];
config.resolver.extraNodeModules = {
  "@anuvritti/world": path.resolve(workspace, "packages/world"),
  "@anuvritti/client": path.resolve(workspace, "packages/client"),
};
// The packages export `.ts` directly; Metro must not skip source it thinks is a type file.
config.resolver.sourceExts = [...config.resolver.sourceExts, "ts", "tsx"];

module.exports = config;
