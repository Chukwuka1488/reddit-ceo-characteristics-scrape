export default {
  semi: true,
  tabWidth: 2,
  trailingComma: "all",
  printWidth: 80,
  proseWrap: "always",
  overrides: [
    {
      files: "*.md",
      options: {
        printWidth: 80,
        proseWrap: "always",
      },
    },
    {
      files: ["*.yml", "*.yaml"],
      options: {},
    },
  ],
};
