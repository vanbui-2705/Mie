type SectionEyebrowProps = {
  label: string;
};

export function SectionEyebrow({ label }: SectionEyebrowProps) {
  return (
    <div className="section-eyebrow">
      <div className="section-eyebrow__bar" />
      <span className="section-eyebrow__label">{label}</span>
    </div>
  );
}
