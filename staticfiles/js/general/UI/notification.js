function notify(message, type="success", duration=4000){
    const container = document.getElementById("notification-container");
    if(!container) return;

    const notification = document.createElement("div");
    notification.className = `notification ${type}`;
    notification.textContent = message;

    container.appendChild(notification);

    setTimeout(()=>{
        notification.classList.add("hide");
        setTimeout(()=>notification.remove(), 300);
    }, duration);
}


document.body.addEventListener("showNotification", function (evt) {
    const { message, level } = evt.detail;

    let text = message;

    if (typeof message === "object") {
        text = Object.entries(message)
            .map(([field, messages]) => `${field}: ${messages.join(", ")}`)
            .join("\n");
    }

    notify(text, level);
});