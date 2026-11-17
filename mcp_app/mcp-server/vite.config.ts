import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// INPUT is set by `npm run build` through cross-env, so the same command works on Windows, macOS and Linux.
const INPUT = process.env.INPUT;
if (!INPUT) {
  throw new Error("INPUT is not set: run `npm run build`.");
}

export default defineConfig({
  plugins: [viteSingleFile()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: { input: INPUT },
  },
});
