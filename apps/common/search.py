from models import User


def users_from_query(query):
    names = User.query.order_by(User.name)
    emails = User.query.order_by(User.email)

    def escape(like):
        return like.replace("^", "^^").replace("%", "^%")

    def name_match(pattern, query):
        return names.filter(User.name.ilike(pattern.format(query), escape="^")).limit(10).all()

    def email_match(pattern, query):
        return emails.filter(User.email.ilike(pattern.format(query), escape="^")).limit(10).all()

    fulls = []
    starts = []
    contains = []
    query = query.lower()
    words = list(map(escape, filter(None, query.split(" "))))

    if " " in query:
        fulls += name_match("%{0}%", "%".join(words))
        fulls += email_match("%{0}%", "%".join(words))

    for word in words:
        starts += name_match("{0}%", word)
        contains += name_match("%{0}%", word)

    for word in words:
        starts += email_match("{0}%", word)
        contains += email_match("%{0}%", word)

    # make unique, but keep in order
    users = list(dict.fromkeys(fulls + starts + contains))[:10]
    return users
