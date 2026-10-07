(() => {
    const viewer = document.getElementById('gift-image-viewer');
    const image = viewer.querySelector('.gift-image-full');
    const title = document.getElementById('gift-image-title');
    let opener;
    document.querySelectorAll('[data-gift-image]').forEach(button => {
        button.addEventListener('click', () => {
            opener = button;
            image.src = button.dataset.giftImage;
            image.alt = button.dataset.giftName;
            title.textContent = button.dataset.giftName;
            viewer.showModal();
            document.documentElement.classList.add('gift-viewer-open');
        });
    });
    viewer.querySelector('.gift-image-close').addEventListener('click', () => viewer.close());
    viewer.addEventListener('click', event => {
        const bounds = viewer.getBoundingClientRect();
        if (event.target === viewer && (event.clientX < bounds.left || event.clientX > bounds.right ||
            event.clientY < bounds.top || event.clientY > bounds.bottom)) viewer.close();
    });
    viewer.addEventListener('close', () => {
        document.documentElement.classList.remove('gift-viewer-open');
        image.removeAttribute('src');
        opener?.focus();
    });
})();
