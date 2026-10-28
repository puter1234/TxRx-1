import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import InspectionImage from "../components/InspectionImage";
afterEach(cleanup);
it("switches same-frame raw, model inputs and detected regions without a new inspection", () => {
  render(<InspectionImage src="/api/bench/ocr/frames/frozen" diagnostics={{locator: "yolo26", source_width: 8000, source_height: 6000,
    detection_width: 4000, detection_height: 3000, stages: [], tags: [{roi: [10,20,100,200]}],
    texts: [{quad: [[20,30],[100,30],[100,40],[20,40]]}], regions: [{quad: [[40,50],[120,50],[120,100],[40,100]],stage: "yolo26"}]}}/>);
  expect(screen.getByAltText("검사에 사용한 원본 사진").getAttribute("src")).toBe("/api/bench/ocr/frames/frozen");
  fireEvent.click(screen.getByRole("button", {name: "전처리"}));
  expect(screen.getByAltText("모델 입력 전처리 결과").getAttribute("src")).toBe("/api/bench/ocr/frames/frozen?view=tag_input&region=0");
  fireEvent.click(screen.getByRole("button", {name: "바코드 입력 1"}));
  expect(screen.getByAltText("모델 입력 전처리 결과").getAttribute("src")).toContain("view=barcode_input&region=0");
  fireEvent.click(screen.getByRole("button", {name: "검출 결과"}));
  const overlay = screen.getByRole("img", {name: "검출한 바코드 위치"});
  expect(overlay.querySelector("rect")?.getAttribute("x")).toBe("20");
  expect(overlay.querySelectorAll("polygon").length).toBe(2);
  fireEvent.click(screen.getByRole("button", {name: "원본"}));
  expect(screen.queryByRole("img", {name: "검출한 바코드 위치"})).toBeNull();
  expect(screen.getByAltText("검사에 사용한 원본 사진").getAttribute("src")).toBe("/api/bench/ocr/frames/frozen");
});
it("does not offer model inputs for a different locator", () => {
  render(<InspectionImage src="/frame" diagnostics={{locator: "stripes", stages: []}}/>);
  expect(screen.getByRole("button", {name: "전처리"})).toHaveProperty("disabled", true);
});
