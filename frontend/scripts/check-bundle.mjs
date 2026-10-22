import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
const files = readdirSync("dist", { recursive: true }).map(String).filter((file) => /\.(js|css|html)$/.test(file));
const bundle = files.map((file) => readFileSync(join("dist", file), "utf8")).join("\n");
const forbidden = ["ANTHROPIC", "LANGSMITH", "JEV", "API_KEY", /(?:secret|token|key)\s*[:=]\s*['\"][^'\"]+/i];
const found = forbidden.find((pattern) => bundle.match(pattern));
if (found) throw new Error(`Forbidden secret-like bundle content: ${found}`);
if (bundle.includes("VITE_API_BASE_URL")) throw new Error("VITE_API_BASE_URL name leaked instead of being baked in");
console.log("bundle contains no forbidden secret markers");
