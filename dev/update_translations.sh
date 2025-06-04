pybabel extract -F babel.cfg -o locales/telecounter.pot .
sed -i 's/Report-Msgid-Bugs-To: EMAIL@ADDRESS/Report-Msgid-Bugs-To: mail@artiekra.org/' locales/telecounter.pot
find locales/ -name "*.po~" -delete
for f in locales/*.po; do msgmerge --update "$f" locales/telecounter.pot; done

find locales/ -name "*.po~" -delete
