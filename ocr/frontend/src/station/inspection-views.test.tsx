import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import InspectionImage from "../components/InspectionImage";
afterEach(cleanup);
it("switches same-frame raw, model inputs and detected regions without a new inspection", () => {
  render(<InspectionImage src="/api/bench/ocr/frames/frozen" diagnostics={{locator: "yolo26", source_width: 8000, source_height: 6000,
    detection_width: 4000, detection_height: 3000, stages: [], tags: [{roi: [10,20,100,200]}],
    ocr_preprocessing: {mode: "green_gain", gain: 3.5, width: 8000, height: 6000, ms: 5},
    texts: [{quad: [[20,30],[100,30],[100,40],[20,40]]}], regions: [{quad: [[40,50],[120,50],[120,100],[40,100]],stage: "yolo26"}]}}/>);
  expect(screen.getByAltText("검사에 사용한 원본 사진").getAttribute("src")).toBe("/api/bench/ocr/frames/frozen");
  fireEvent.click(screen.getByRole("button", {name: "전처리"}));
  expect(screen.getByAltText("모델 입력 전처리 결과").getAttribute("src")).toBe("/api/bench/ocr/frames/frozen?view=tag_input&region=0");
  fireEvent.click(screen.getByRole("button", {name: "바코드 입력 1"}));
  expect(screen.getByAltText("모델 입력 전처리 결과").getAttribute("src")).toContain("view=barcode_input&region=0");
  fireEvent.click(screen.getByRole("button", {name: "OCR 전처리"}));
  expect(screen.getByAltText("모델 입력 전처리 결과").getAttribute("src")).toContain("view=ocr_input&region=0");
  fireEvent.click(screen.getByRole("button", {name: "검출 결과"}));
  const overlay = screen.getByRole("img", {name: "검출한 바코드 위치"});
  expect(overlay.querySelector("rect")?.getAttribute("x")).toBe("20");
  expect(overlay.querySelectorAll("polygon").length).toBe(2);
  expect(overlay.querySelector("text")?.textContent).toBe("1");
  expect(screen.getByAltText("검출된 바코드 1").getAttribute("src")).toBe("/api/bench/ocr/frames/frozen?view=barcode_crop&region=0");
  fireEvent.click(screen.getByRole("button", {name: "원본"}));
  expect(screen.queryByRole("img", {name: "검출한 바코드 위치"})).toBeNull();
  expect(screen.getByAltText("검사에 사용한 원본 사진").getAttribute("src")).toBe("/api/bench/ocr/frames/frozen");
});
it("selects each detected barcode and shows zero when only a tag was detected", () => {
  const diagnostics = {locator: "yolo26" as const, stages: [], source_width: 8000, source_height: 6000,
    tags: [{roi: [10,20,100,200]}], regions: [0, 1].map(i => ({quad: [[i,0],[i+1,0],[i+1,1],[i,1]], stage: "yolo26"}))};
  const view = render(<InspectionImage src="/frame" diagnostics={diagnostics}/>);
  fireEvent.click(screen.getByRole("button", {name: "검출 결과"}));
  expect(screen.getByText("바코드 2개")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", {name: "바코드 2"}));
  expect(screen.getByAltText("검출된 바코드 2").getAttribute("src")).toBe("/frame?view=barcode_crop&region=1");
  view.rerender(<InspectionImage src="/frame" diagnostics={{...diagnostics, regions: []}}/>);
  expect(screen.getByText("검출된 바코드가 없습니다.")).toBeTruthy();
  expect(screen.queryByAltText("검출된 바코드 2")).toBeNull();
});
it("does not offer model inputs for a different locator", () => {
  render(<InspectionImage src="/frame" diagnostics={{locator: "stripes", stages: []}}/>);
  expect(screen.getByRole("button", {name: "전처리"})).toHaveProperty("disabled", true);
});
