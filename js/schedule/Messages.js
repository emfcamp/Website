import React, { useState, useEffect } from 'react';

const messageReloadInterval = 5; // Minutes

function Messages() {
  const [messages, setMessages] = useState([]);

  function reloadMessages() {
    fetch(`/api/schedule_messages`)
      .then(response => response.json())
      .then(body => {
        setMessages(body);
      });
  }

  useEffect(() => {
    let intervalHandle = setInterval(reloadMessages, messageReloadInterval * 6000);
    reloadMessages();

    return () => { clearInterval(intervalHandle) }
  }, []);

  return (
    <div className="messages panel panel-primary">
      <div className="panel-heading">
        <h2 className="panel-title">Important Messages</h2>
      </div>
      <ul className="list-group">
        { messages.map(m => <li className="list-group-item" key={m.id}>{m.body}</li>) }
      </ul>
    </div>
  );
}

export default Messages;
