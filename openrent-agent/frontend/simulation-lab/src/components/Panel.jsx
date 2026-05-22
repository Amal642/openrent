export default function Panel({ title, children, actions }) {
  return (
    <section className="panel">
      <header className="panel-header">
        <h2>{title}</h2>
        {actions ? <div>{actions}</div> : null}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}
