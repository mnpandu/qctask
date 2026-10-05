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
    const openReporting = () => {
        if (window.location.hash !== '#reporting') return;
        const tab = [...document.querySelectorAll('button[role="tab"]')]
            .find(button => button.textContent.trim() === 'Reporting');
        if (tab && tab.getAttribute('aria-selected') !== 'true') tab.click();
    };
    window.addEventListener('hashchange', openReporting);
    document.addEventListener('click', event => {
        if (event.target.closest('a[href="#reporting"]')) setTimeout(openReporting, 0);
    });
    setTimeout(openReporting, 500);
    let scheduled = false;
    new MutationObserver(() => {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(() => { scheduled = false; alignRows(); });
    }).observe(document.body, {childList: true, subtree: true, characterData: true});
    alignRows();
}
