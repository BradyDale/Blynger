import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

function run(program, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(program, args, { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
    let error = "";
    child.stderr.on("data", chunk => { error += chunk; });
    child.on("error", reject);
    child.on("close", code => code === 0 ? resolve() : reject(new Error(error || `${program} exited ${code}`)));
  });
}

export default {
  id: "blynger",
  name: "Blynger",
  async version() {
    const text = await import("node:fs/promises").then(fs => fs.readFile(path.join(root, "version.py"), "utf8"));
    return text.match(/APP_VERSION=['\"]([^'\"]+)/)?.[1] ?? "unknown";
  },
  async samples(dir) {
    const python = process.env.BLYNGER_PYTHON || "python3";
    await run(python, [path.join(root, "conformance_fixture.py"), dir]);
  },
  async staticFields() {
    return {
      item: {
        "author": [true, true, "Stored as an opaque object by Reader"],
        "transclusions[]": [true, true, "Retained with imported item snapshots"],
        "stub_of": [true, true, "Retained and used by Stub"],
        "forked_from": [true, true, "Retained and used by Fork"],
        "generated[]": [true, true, "Retained for Reader disclosure"]
      },
      pinned: {
        "stub_of": [true, true, "Frozen with the pinned artifact"],
        "forked_from": [true, true, "Frozen with the pinned artifact"],
        "transclusions": [true, true, "Frozen with the pinned artifact"],
        "generated": [true, true, "Frozen with the pinned artifact"]
      }
    };
  }
};
