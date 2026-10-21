const finite = (value: string | number | null | undefined) => {
  const numberValue = Number(value);
  return value === null || value === undefined || !Number.isFinite(numberValue) ? null : numberValue;
};

export const money = (value: string | number | null | undefined) => {
  const parsed = finite(value);
  return parsed === null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(parsed);
};
export const percent = (value: string | number | null | undefined) => {
  const parsed = finite(value);
  return parsed === null ? "—" : new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 2 }).format(parsed);
};
export const timestamp = (value: string | null | undefined) => {
  if (!value || Number.isNaN(Date.parse(value))) return "—";
  return new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" }).format(new Date(value));
};
export const number = (value: string | number | null | undefined) => {
  const parsed = finite(value);
  return parsed === null ? "—" : new Intl.NumberFormat("en-US", { maximumFractionDigits: 8 }).format(parsed);
};
