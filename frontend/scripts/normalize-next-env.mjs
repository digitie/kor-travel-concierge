import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const nextEnvPath = join(scriptDir, "..", "next-env.d.ts");
const routeImportPattern = /^import "\.\/\.next\/(?:dev\/)?types\/routes\.d\.ts";\r?\n/m;
const routeImport = 'import "./.next/dev/types/routes.d.ts";\n';

const source = await readFile(nextEnvPath, "utf8");
const normalized = routeImportPattern.test(source)
  ? source.replace(routeImportPattern, routeImport)
  : source.replace(
      '/// <reference types="next/image-types/global" />\n',
      `/// <reference types="next/image-types/global" />\n${routeImport}`,
    );

if (normalized !== source) {
  await writeFile(nextEnvPath, normalized);
}
