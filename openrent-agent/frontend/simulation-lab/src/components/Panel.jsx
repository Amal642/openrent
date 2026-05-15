export default function Panel({ title, children, actions }) {
  return (
    <section className="panel">
      <header className="panel-header">
        <div>
          <p className="panel-kicker">simulation lab</p>
          <h2>{title}</h2>
        </div>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}
