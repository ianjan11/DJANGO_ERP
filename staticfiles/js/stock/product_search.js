document.addEventListener('DOMContentLoaded', function() {

    // Function to fetch and update products
    function loadProducts() {
        const search = document.querySelector('input[name="search"]').value;
        const category = document.querySelector('select[name="category"]').value;
        const stock_status = document.querySelector('select[name="stock_status"]').value;
        const wrapper = document.getElementById('product-table');

        const ajaxUrl = wrapper.dataset.url;


        const params = new URLSearchParams({
            search: search,
            category: category,
            stock_status: stock_status
        });

        fetch(ajaxUrl + "?" + params.toString())
            .then(response => response.text())
            .then(html => {
                document.getElementById('product-table').innerHTML = html;
            })
            .catch(error => {
                console.error('Error loading products:', error);
            });
    }

    // Event listeners
    const searchInput = document.querySelector('input[name="search"]');
    const categorySelect = document.querySelector('select[name="category"]');
    const stockSelect = document.querySelector('select[name="stock_status"]');

    searchInput.addEventListener('input', loadProducts);
    categorySelect.addEventListener('change', loadProducts);
    stockSelect.addEventListener('change', loadProducts);
});
