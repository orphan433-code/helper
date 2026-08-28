export type BankBinRow = {
  id: string;
  name: string;
  visa: string[];
  mastercard: string[];
};

export const BANK_BINS: BankBinRow[] = [
  {
    id: "bog",
    name: "Bank of Georgia",
    visa: ["411634", "414051", "414052", "429594"],
    mastercard: ["516746", "531125", "548888", "558328"],
  },
  {
    id: "basis",
    name: "Basisbank",
    visa: ["499864"],
    mastercard: [],
  },
  {
    id: "liberty",
    name: "Liberty Bank",
    visa: ["412570", "412571"],
    mastercard: ["532434", "537524"],
  },
  {
    id: "tbc",
    name: "TBC Bank",
    visa: ["400881", "412742", "415479", "431570", "431571"],
    mastercard: ["516185", "518974", "521026", "537493"],
  },
];

export function formatBinMask(bin: string): string {
  const d = bin.replace(/\D/g, "").slice(0, 6);
  const padded = d.padEnd(6, "*");
  return `${padded.slice(0, 4)} ${padded.slice(4)}** ****`;
}

export function buildBinCommand(
  action: "decline" | "redirect",
  bins: string[],
): string {
  const verb = action === "redirect" ? "редирект" : "отмени";
  const list = bins.join(", ");
  return `${verb} все сделки ${list}`.trim();
}
