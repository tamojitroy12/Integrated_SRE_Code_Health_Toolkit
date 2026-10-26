import next from "eslint-config-next";

const config = [
  ...next,
  {
    ignores: [".next/**", "node_modules/**", "coverage/**", "playwright-report/**", "test-results/**", "next-env.d.ts"],
  },
  {
    rules: {
      // LLM output, advisories and code snippets must never be injected as HTML (TH-21).
      "react/no-danger": "error",
      "no-restricted-syntax": [
        "error",
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: "Render untrusted text as text." },
      ],
    },
  },
];

export default config;
