import requests

res = requests.get('https://www.emfcamp.org/admin/stats')
res.raise_for_status()

data = dict(map(lambda t: t.split(':'), res.text.split(' ')))

submission = []

for key, admits in [('full', 'full'), ('kids', 'kid')]:
	submission.append("tickets,type=%s,status=all value=%s" % (
			key, data[admits]))
	submission.append("tickets,type=%s,status=bought value=%s" % (
			key, data[admits + "_paid"]))
	submission.append("tickets,type=%s,status=unpaid value=%s" % (
			key, data[admits + "_unexpired"]))
	submission.append("tickets,type=%s,status=expired value=%s" % (
			key, data[admits + "_expired"]))

submission.append("tickets,type=full,status=gocardless_unpaid value=%s" % (
		  data["full_gocardless_unexpired"]))
submission.append("tickets,type=full,status=banktransfer_unpaid value=%s" % (
		  data["full_banktransfer_unexpired"]))

submission.append("tickets,type=parking,status=bought value=%s" % (
		  data["car_paid"]))
submission.append("tickets,type=campervan,status=bought value=%s" % (
		  data["campervan_paid"]))

submission.append("people,status=registered value=%s" % (
		  data["users"]))
submission.append("people,status=checked_in value=%s" % (
		  data["checked_in"]))
submission.append("people,status=badged_up value=%s" % (
		  data["badged_up"]))

submission.append("proposals,status=received value=%s" % (
		  data["proposals"]))

res = requests.post("http://localhost:8086/write?db=emf2016", data="\n".join(submission))
res.raise_for_status()

