() => {
    const alignRows = () => {
        document.querySelectorAll('.task-summary > button.label-wrap > span:not(.icon)').forEach(label => {
            if (label.children.length) return;
            const values = label.textContent.split('	');
            if (values.length !== 7) return;
            label.replaceChildren(...values.map(value => {
                const cell = document.createElement('span');
                cell.textContent = value;
                return cell;
            }));
        });
        document.querySelectorAll('.claim-review-summary > button.label-wrap > span:not(.icon)').forEach(label => {
            if (label.children.length) return;
            const values = label.textContent.split('\t');
            if (values.length !== 12) return;
            label.replaceChildren(...values.map(value => {
                const cell = document.createElement('span');
                cell.textContent = value;
                return cell;
            }));
        });
    };
    let scheduled = false;
    new MutationObserver(() => {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(() => { scheduled = false; alignRows(); });
    }).observe(document.body, {childList: true, subtree: true, characterData: true});
    alignRows();
}
