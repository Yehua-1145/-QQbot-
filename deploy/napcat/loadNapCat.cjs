const path = require("node:path");
const { pathToFileURL } = require("node:url");
if (process.argv.includes("--no-sandbox")) {
    import(pathToFileURL(path.join(__dirname, "napcat/napcat.mjs")).href);
} else {
    const original = require("./package.napcat-original.json");
    require(path.resolve(__dirname, original.main));
    setTimeout(() => {
        global.launcher.installPathPkgJson.main = original.main;
    }, 0);
}