export default function SetupCard({ setup }) {
  if (!setup) return null;
  const { property, landlord_brief: brief } = setup;

  return (
    <section className="setup-card">
      <div className="setup-card-header">
        <span className="setup-card-eyebrow">New enquiry</span>
        <h2>{property?.title || "Property listing"}</h2>
      </div>

      {property ? (
        <div className="setup-block setup-block--full">
          <p className="setup-block-meta">
            {property.bedrooms ? `${property.bedrooms}-bed` : ""}
            {property.rent_pcm
              ? ` · £${property.rent_pcm.toLocaleString()} pcm`
              : ""}
            {property.furnished !== undefined
              ? ` · ${property.furnished ? "furnished" : "unfurnished"}`
              : ""}
            {property.available_from
              ? ` · available ${property.available_from}`
              : ""}
          </p>
        </div>
      ) : null}

      {brief && (brief.phone_number || brief.viewing_availability) ? (
        <div className="setup-brief">
          <div className="setup-brief-facts">
            {brief.phone_number ? (
              <div className="setup-fact">
                <span>Your phone number</span>
                <strong>{brief.phone_number}</strong>
              </div>
            ) : null}
            {brief.viewing_availability ? (
              <div className="setup-fact">
                <span>Your availability</span>
                <strong>{brief.viewing_availability}</strong>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
