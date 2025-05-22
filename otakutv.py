import asyncio
import aiohttp
from bs4 import BeautifulSoup


class Anime:
    def __init__(self):
        self.name = None
        self.active = None
        self.synopsis = None
        self.year = None
        self.image = None
        self.episodes = []


class AnimeSearch:
    def __init__(self, name, image, url):
        self.name = name
        self.image = image
        self.url = url


class Image:
    def __init__(self, src):
        self.src = src


class SearchArray:
    def __init__(self, page):
        self.page = page
        self.data = []


class OtakuTV:
    def __init__(self):
        self.base_url = "https://www1.otakustv.com"

    async def _fetch_html(self, url):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                return await response.text()

    def _parse_html(self, html):
        return BeautifulSoup(html, "html.parser")

    async def get_anime(self, anime):
        animename = anime.lower().replace(" ", "-")
        url = f"{self.base_url}/anime/{animename}"

        try:
            html = await self._fetch_html(url)
            soup = self._parse_html(html)

            anime_obj = Anime()
            anime_obj.name = soup.select_one("div.inn-text h1.text-white").text
            status_text = soup.select_one("span.btn-anime-info").text.strip()
            anime_obj.active = status_text != "Finalizado"
            anime_obj.synopsis = soup.select_one("div.modal-body").text.strip()
            anime_obj.year = soup.select_one("span.date").text.replace(
                " Estreno: ", "Se estreno: "
            )

            image_elements = soup.select("div.img-in img")
            if len(image_elements) > 1:
                anime_obj.image = image_elements[1].get("src")

            episode_elements = soup.select(
                "div.tabs div.tab-content div.tab-pane div.pl-lg-4 div.container-fluid div.row div.col-6"
            )
            for episode in episode_elements:
                title = episode.find("p").find("span").text
                url = episode.find("a").get("href")
                anime_obj.episodes.append({"title": title, "url": url})

            return anime_obj
        except Exception as e:
            return e

    async def get_coming_soon(self):
        url = f"{self.base_url}/"
        try:
            html = await self._fetch_html(url)
            soup = self._parse_html(html)
            animes = []
            anime_elements = soup.select(
                "div.pronto div.base-carusel div.carusel_pronto div.item"
            )
            for element in anime_elements:
                name = element.find("h2").text.strip()
                date_release = element.find("p").text.replace("Estreno: ", "")
                link = (
                    element.find("a")
                    .get("href")
                    .replace("https://www1.otakustv.com/anime/", "/anime/otakuTV/")
                )
                cover_img = element.find("img").get("data-src")
                animes.append(
                    {
                        "name": name,
                        "dateRelease": date_release,
                        "link": link,
                        "coverImg": cover_img,
                    }
                )
            return animes
        except Exception as e:
            return e

    async def get_anime_latino(self):
        url = f"{self.base_url}/"
        try:
            html = await self._fetch_html(url)
            soup = self._parse_html(html)

            animes = []
            anime_elements = soup.select("div.latino div.item ")
            for element in anime_elements:
                name = element.find("h2").text.strip()
                url = (
                    element.find("a")
                    .get("href")
                    .replace("https://www1.otakustv.com/anime/", "/anime/otakuTV/")
                )
                cover_img = element.find("a").find("img").get("data-src")
                episodes_number = element.find("p").text.replace("video(s)", "").strip()
                animes.append(
                    {
                        "name": name,
                        "url": url,
                        "coverImg": cover_img,
                        "episodesNumber": episodes_number,
                    }
                )
            return animes

        except Exception as e:
            return e

    async def get_anime_new(self):
        url = f"{self.base_url}/"
        try:
            html = await self._fetch_html(url)
            soup = self._parse_html(html)
            animes = []
            anime_elements = soup.select("div.reciente div.carusel_reciente .item ")
            for element in anime_elements:
                name = element.find("h2").text.strip()
                url = (
                    element.find("a")
                    .get("href")
                    .replace("https://www1.otakustv.com/anime/", "/anime/otakuTV/")
                )
                cover_img = element.find("a").find("img").get("data-src")
                episodes_number = element.find("p").text.replace("video(s)", "").strip()
                animes.append(
                    {
                        "name": name,
                        "url": url,
                        "coverImg": cover_img,
                        "episodesNumber": episodes_number,
                    }
                )
            return animes
        except Exception as e:
            return e

    async def get_anime_ranking(self):
        url = f"{self.base_url}/"
        try:
            html = await self._fetch_html(url)
            soup = self._parse_html(html)
            anime_ranking = []
            anime_elements = soup.select(
                "div.ranking div.base-carusel div.carusel_ranking div.item "
            )
            for element in anime_elements:
                title = element.find("a").find("h2").text
                cover_img = element.find("a").find("img").get("src")
                link_to = (
                    element.find("a")
                    .get("href")
                    .replace("https://www1.otakustv.com/anime/", "/anime/otakuTV/")
                )
                anime_ranking.append(
                    {
                        "title": title,
                        "coverImg": cover_img,
                        "linkTo": link_to,
                    }
                )
            return anime_ranking
        except Exception as e:
            return e

    async def get_users_active(self):
        url = f"{self.base_url}/"
        try:
            html = await self._fetch_html(url)
            soup = self._parse_html(html)
            users = []
            user_elements = soup.select("div.user_act div.item ")
            for element in user_elements:
                link_to_perfil = (
                    element.find("a")
                    .get("href")
                    .replace(
                        "https://www1.otakustv.com/perfil/",
                        "/anime/otakuTV/profile/",
                    )
                )
                name = element.find("h2").text
                ranking = element.find("p").text
                users.append(
                    {
                        "linkToPerfil": link_to_perfil,
                        "name": name,
                        "ranking": ranking,
                    }
                )
            return users
        except Exception as e:
            return e

    async def search(self, name):
        url = f"{self.base_url}/buscador?q={name}"
        try:
            html = await self._fetch_html(url)
            soup = self._parse_html(html)
            animes = SearchArray(1)
            test = []
            anime_elements = soup.select(".animes_lista .row .col-6")
            for element in anime_elements:
                anime_name = element.find("p", class_="font-GDSherpa-Bold").text
                image_src = element.find("img").get("src")
                anime_url = element.find("a").get("href")
                animes.data.append(AnimeSearch(anime_name, Image(image_src), anime_url))

            return animes
        except Exception as e:
            return e

    async def get_anime_server(self, name):
        anime_name = name.lower().replace(" ", "-")
        url = f"{self.base_url}/anime/{anime_name}/episodio-1"
        try:
            html = await self._fetch_html(url)
            soup = self._parse_html(html)

            return soup.prettify()

        except Exception as e:
            return e


async def main():
    otaku_tv = OtakuTV()
    #anime_data = await otaku_tv.get_anime("bocchi the rock")
    #print("Anime Data:", anime_data)

    #coming_soon_data = await otaku_tv.get_coming_soon()
    #print("Coming Soon:", coming_soon_data)

    #anime_latino = await otaku_tv.get_anime_latino()
    #print("Anime Latino:", anime_latino)

    #anime_new = await otaku_tv.get_anime_new()
    #print("Anime New:", anime_new)

    #anime_ranking = await otaku_tv.get_anime_ranking()
    #print("Anime Ranking:", anime_ranking)

    #active_users = await otaku_tv.get_users_active()
    #print("Active users:", active_users)

    #search_results = await otaku_tv.search("bocchi")
    #for results in search_results.data:
    #    print("Search results:", results)

    server_data = await otaku_tv.get_anime_server("bocchi the rock")
    print("server", server_data)


if __name__ == "__main__":
    asyncio.run(main())
