import React, { useState } from 'react';
import octicons from '@primer/octicons';
import nl2br from 'react-nl2br';

function Icon({ name, className, size, label }) {
  let svg = octicons[name].toSVG({ 'aria-label': label, width: size, height: size });
  return <span className={ className } dangerouslySetInnerHTML={ { __html: svg } } title={ label } />;
}

function NoRecordingIcon({ noRecording }) {
  if (!noRecording) { return null; }

  return (
    <div className="no-recording">
      <Icon name="device-camera" className="camera" size="16" />
      <Icon name="circle-slash" className="slash" size="32" label="Not recorded" />
    </div>
  );
}

function FavouriteIcon({ isFavourite }) {
  if (!isFavourite) { return null; }

  return <Icon name="star" className="favourite" size="32" label="Favourite" />;
}

function FamilyFriendlyIcon({ isFamilyFriendly }) {
  if (!isFamilyFriendly) { return null; }

  return <Icon name="people" className="family-friendly" size="32" label="Family Friendly" />;
}

function ContentWarningIcon({ hasContentWarning }) {
  if (!hasContentWarning) { return null; }

  return <Icon name="alert-fill" className="content-warning" size="32" label="Content Warning" />;
}

function RequiresTicketIcon({ requiresTicket }) {
  if (!requiresTicket) { return null; }

  return (<span title="This workshop requires you sign up for a ticket">🎟</span>);
}

function EventIcons({ noRecording, isFavourite, isFamilyFriendly, hasContentWarning, requiresTicket }) {
  return (
    <div className="event-icons">
      <NoRecordingIcon key='no-recording' noRecording={ noRecording } />
      <FavouriteIcon key='favourite' isFavourite={ isFavourite } />
      <FamilyFriendlyIcon key='family-friendly' isFamilyFriendly={ isFamilyFriendly } />
      <ContentWarningIcon key='content-warning' hasContentWarning={ hasContentWarning } />
      <RequiresTicketIcon key='requires-ticket' requiresTicket={ requiresTicket } />
    </div>
  );
}

function FavouriteButton({ event, toggleFavourite, authenticated }) {
  if (!authenticated) {
    return <p><strong>Log in to add favourites</strong></p>;
  }

  let label = event.is_fave ? 'Remove From Favourites' : 'Add to Favourites';

  return (
    <button className="btn btn-warning" onClick={ () => toggleFavourite(event) }>{ label }</button>
  );
}

function AdditionalInformation({ label, value }) {
  if (value === null || value === undefined || value == "Unspecified" || value == "") { return null; }

  return <p className="additional-information"><strong>{ label }:</strong> { value }</p>
}

function Event({ event, toggleFavourite, authenticated }) {
  let [expanded, setExpanded] = useState(false);

  function humanTypeName(type) {
    if (type == "youthworkshop") { return "Youth Workshop" }

    return type.charAt(0).toUpperCase() + type.slice(1);
  }

  let metadata = [
    `${event.startTime.toFormat('HH:mm')} to ${event.endTime.toFormat('HH:mm')}`,
    event.venue,
    humanTypeName(event.type),
  ].filter(i => { return i !== null && i !== '' }).join(' | ');

  function eventDetails() {
    if (!expanded) { return null; }

    return (
      <div className="event-details">
        <AdditionalInformation label="Maximum attendees" value={ event.attendees } />
        <AdditionalInformation label="Content warning" value={ event.content_note } />
        <AdditionalInformation label="Age range" value={ event.age_range } />
        <AdditionalInformation label="Cost" value={ event.cost } />
        <AdditionalInformation label="Required equipment" value={ event.equipment } />

        <p>{ nl2br(event.description) }</p><p><a href={ event.link } target="_blank"><Icon name="link" size="16" label="Link to this content" />Details</a></p>
        <FavouriteButton event={ event } toggleFavourite={ toggleFavourite } authenticated={ authenticated } />
      </div>
    );
  }

  function toggleExpanded() {
    setExpanded(!expanded);
  }

  const cfpClass = event.is_from_cfp ? "cfp" : "user-submitted";

  return (
    <div className={ ["schedule-event", cfpClass ].join(" ") }>
      <div className="event-synopsis" onClick={ toggleExpanded }>
        <div className="event-data">
          <h3 title={ event.title }>{ event.title }</h3>
          <p>{ metadata } | <span className="speaker">{ event.speaker }</span></p>
        </div>
        <EventIcons noRecording={ event.noRecording } isFavourite={ event.is_fave } isFamilyFriendly={ event.is_family_friendly } hasContentWarning={ event.content_note && event.content_note != ''} requiresTicket={ event.requires_ticket } />
      </div>
      { eventDetails() }
    </div>
  );
}

function Hour({ hour, content, newDay, toggleFavourite, authenticated }) {
  if (content.length === 0) { return null; }

  return (
    <div className="schedule-day">
      { newDay && <h2>{ hour.weekdayLong }</h2> }
      <div className="schedule-hour">
        <h3 id={hour.toISO()}>{hour.toFormat('HH:mm')}</h3>
        <div className="schedule-events-container">
          { content.map(event => <Event key={event.id} event={event} toggleFavourite={ toggleFavourite } authenticated={ authenticated } />) }
        </div>
      </div>
    </div>
  );
}

function Calendar({ schedule, toggleFavourite, authenticated }) {
  let currentDay = null;
  let previousDay = null;
  let newDay = false;

  return schedule.hoursWithContent.map(hour => {
    currentDay = hour.toFormat('DD');
    newDay = currentDay != previousDay;
    previousDay = currentDay;

    return (
      <Hour key={hour.toISO()} hour={hour} newDay={ newDay } content={schedule.contentForHour(hour)} toggleFavourite={ toggleFavourite } authenticated={ authenticated } />
    );
  });
}

export default Calendar;
