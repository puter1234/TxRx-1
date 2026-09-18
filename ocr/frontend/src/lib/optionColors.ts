import type { Option } from "../station/shared";

export const isColorOption = (option: Option) =>
  option.display === "colors" ||
  (option.display == null && option.key === "color");

export const validColor = (value: string | undefined): value is string =>
  typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value);

export function colorInk(hex: string): string {
  const channels = [1, 3, 5].map((offset) => {
    const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  const light =
    channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  return (light + 0.05) / 0.05 >= 1.05 / (light + 0.05) ? "#000000" : "#FFFFFF";
}

export function optionColorStyle(option: Option, value: string) {
  const color = isColorOption(option) ? option.colors?.[value] : undefined;
  return validColor(color)
    ? { backgroundColor: color, color: colorInk(color) }
    : undefined;
}
