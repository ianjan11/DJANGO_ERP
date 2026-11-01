(() => {

        Btn = document.getElementById('insert-row-btn')

        function insert_row(e){

        tbody = document.getElementById('#table-body')
    
        if (!tBody) return;

        const newRow = 
            "<tr     hx-get="{% url 'accounting:account_detail' account.id %}"
                hx-target="#accounting-display"
                hx-push-url="true">
            <td style="text-align: center;">
                <input type="checkbox"
                       name="account_ids"
                       value="{{ account.id }}"
                       data-select-row
                       data-row-id="{{ account.id }}">
            </td>

            <td class="td-mono">   
            {{ account_form.code }}
        {% if account_form.code.errors %}
          <div class="invalid-feedback d-block">{{ account_form.code.errors|first }}</div>
        {% endif %}
        </td>
        <td class="td-primary">
        {{ account_form.name }}
         </td>
            <td>{{ account_form.description }}</td>
            <td class="col-right">{{ account_form.account_type }}</td>
            <td>{{ account_form.currency }}</td>
            <td>{{ account_form.Parent }}</td>
            <td>{{ account_form.internal_type }}</td>
            <td>{{ account_form.is_control }}</td>
            <td>{{ account_form.is_active }}</td>
            <td>{{ account_form.allow_reconciliation }}</td>
        </tr>
        {% empty %}
        <tr>"

        $("tbody").first().prepend(newRow);

            }



    }


);