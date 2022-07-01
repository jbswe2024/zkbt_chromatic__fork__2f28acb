from ..imports import *
from ..resampling import bintoR
from ..version import __version__


class PHOENIXLibrary:
    # downloaded files will be stored in "~/.{_cache_label}"
    _cache_label = "chromatic"

    # these coordinates are needed to index the grid (in this order)
    _keys_for_indexing = ["temperature", "logg", "metallicity"]

    # the resolutions available as precalculated grids
    _available_resolutions = [
        3,
        10,
        30,
        100,
        300,
        1000,
        3000,
        10000,
        30000,
        100000,
    ]

    def __init__(self, photons=True):
        """
        Initialize a PHOENIX model library to provide easy
        access to model stellar spectra at resolutions up
        to R=100000.

        Parameters
        ----------
        directory : str
            The path to a directory where *new* library grids
            will be created. This will only be used if you're
            calling the super secret `._create_grids` functions
            to download raw PHOENIX spectrum files and compile
            them into a new library. Most users can just
            not worry about this!
        photons : bool
            Should the units be in photons, rather than power?
            If True, spectrum units will be photons/(s * m**2 * nm)
            If False, spectrum units will be J/(s * m**2 * nm)
        """

        # should we use photon units (e.g. photons/s/m**2/nm)?
        # (if not, we'll use flux per wavelength units like W/m**2/nm)
        self._are_the_units_photons = photons

    def _download_grid(self, R, metallicity=0.0, cache=True):
        """
        Download the preprocessed grid for a particular
        resolution, or load it from a cached local file.

        Parameters
        ----------
        R : float
            The resolution of the grid to retrieve
        metallicity : float
            The stellar metallicity (= log10[metals/solar])
        cache : bool
            Once it's downloaded, should we keep it for next time?

        Returns
        -------
        filename : str
            The path to the downloaded local file for the grid.
        """

        # make sure the resolution is reasonable
        if R not in self._available_resolutions:
            raise ValueError(
                f"""
            Your requested resolution of R={R} is not in
            {self._available_resolutions}
            Please pick one of those choices to download.
            """
            )

        # make sure it's a possible R
        assert R in self._available_resolutions

        # download (or find the cached local file)
        basename = self._get_grid_filename(R, metallicity=metallicity)
        url = f"https://casa.colorado.edu/~bertathompson/chromatic/{basename}"
        print(
            f"""
        Downloading pre-processed grid for R={R}, metallicity={metallicity} from
        {url}
        """
        )
        self._local_paths[R] = download_file_with_warning(
            url, pkgname=self._cache_label, cache=cache, show_progress=True
        )
        return self._local_paths[R]

    def _download_raw_data(self, metallicity=0.0, cache=True):
        """
        Make sure the raw data from the online PHOENIX database
        are downloaded to your local computer. (Most users
        shouldn't have to interact with this, unless you
        want to do something particularly fancy.)

        You must be connected to the internet for this to work.
        It may take quite a long time!

        Parameters
        ----------
        metallicity : float
            The stellar metallicity (= log10[metals/solar])
        cache : bool
            Once it's downloaded, should we keep it for next time?
        """

        # create a dictionary to store the local
        self._raw_local_paths = {}

        # where are the raw data located at online?
        self._raw_base_url = "ftp://phoenix.astro.physik.uni-goettingen.de/HiResFITS"

        # get the one shared wavelength array
        self._raw_wavelengths_filename = "WAVE_PHOENIX-ACES-AGSS-COND-2011.fits"
        self._raw_wavelengths_url = "/".join(
            [self._raw_base_url, self._raw_wavelengths_filename]
        )
        warnings.warn(
            f"""
        Downloading (or finding locally) the shared wavelength grid from
        {self._raw_wavelengths_url}
        """
        )
        self._raw_local_paths["wavelengths"] = download_file_with_warning(
            self._raw_wavelengths_url, pkgname=self._cache_label, cache=cache
        )

        # get the index of files in this metallicity's directory
        metallicity_string = self._stringify_metallicity(metallicity)
        self._raw_directory = f"PHOENIX-ACES-AGSS-COND-2011/Z{metallicity_string}"
        self._raw_directory_url = "/".join([self._raw_base_url, self._raw_directory])
        self._raw_local_paths[
            f"index-Z={metallicity_string}"
        ] = download_file_with_warning(
            self._raw_directory_url, pkgname=self._cache_label, cache=cache
        )
        warnings.warn(
            f"""
        Downloading (or finding locally) the index of files from
        {self._raw_directory_url}
        """
        )

        # get the complete list of spectrum files
        self._raw_spectrum_filenames = list(
            ascii.read(self._raw_local_paths[f"index-Z={metallicity_string}"])
            .columns[-1]
            .data
        )
        self._raw_spectrum_urls = [
            "/".join([self._raw_base_url, self._raw_directory, f])
            for f in self._raw_spectrum_filenames
        ]
        N = len(self._raw_spectrum_urls)
        warnings.warn(
            f"""
        Downloading (or finding locally) {N} very large files from
        {self._raw_directory_url}

        If the files aren't already downloaded,
        this might take an annoyingly long time!
        If it crashes due to a timeout,
        try restarting.
        """
        )
        self._current_raw_metallicity = metallicity
        self._raw_downloaded = {}
        for url, file in tqdm(
            zip(self._raw_spectrum_urls, self._raw_spectrum_filenames)
        ):
            self._raw_downloaded[file] = download_file_with_warning(
                url, pkgname=self._cache_label, cache=cache
            )

    def _load_raw_wavelength(self):
        """
        Load in the raw wavelength array.

        Returns
        -------
        wavelength : u.Quantity
            The wavelengths associated with this grid,
            with astropy units of microns.
        """

        # default to the preloaded raw wavelength
        try:
            return self._raw_wavelength

        # load the raw wavelengths and save them for next time
        except AttributeError:
            wavelength_filename = self._raw_local_paths["wavelengths"]
            hdu = fits.open(wavelength_filename)
            wavelength_without_unit = hdu[0].data
            wavelength_unit = u.Angstrom
            wavelength = wavelength_without_unit * wavelength_unit
            self._raw_wavelength = wavelength.to("micron")
            return self._raw_wavelength

    def _load_raw_spectrum(self, filename):
        """
        Load in a raw spectrum array.

        Parameters
        ----------
        filename : string
            The filename of the raw PHOENIX spectrum
        Returns
        -------
        spectrum : u.Quantity
            The spectrum, with astropy units of W/(m**2 nm)
        """
        hdus = fits.open(filename)
        flux_without_unit = hdus[0].data
        flux_unit = u.Unit("erg/(s * cm**2 * cm)")
        flux = flux_without_unit * flux_unit
        return flux.to("W/(m**2 nm)")

    def _stringify_metallicity(self, metallicity):
        """
        Convert a metallicity into a PHOENIX-style string.

        Parameters
        ----------
        metallicity : float
            [Fe/H]-style metallicity (= 0.0 for solar)

        Returns
        -------
        s : string
            The metallicity, as a PHOENIX-style string.
        """
        if metallicity <= 0:
            return f"-{np.abs(metallicity):03.1f}"
        else:
            return f"+{metallicity:03.1f}"

    def _get_Tgz_from_filename(self, filename):
        """
        A helper to get the temperature, logg, and metallicity
        from a PHOENIX spectrum model filename.

        Parameters
        ----------
        filename : string
            The filename of PHOENIX model.

        Returns
        -------
        temperature : float
            Temperature (K)
        logg : float
            log10([surface gravity]/[cm/s**2])
        metallicity : float
            log10([metallicity]/[solar metallicity])
        """

        f = os.path.basename(filename)
        temperature = float(f[3:8])
        logg = float(f[9:13])
        metallicity = float(f[13:17].replace("-0.0", "0.0"))
        return temperature, logg, metallicity

    def _get_filename_from_Tgz(self, temperature, logg, metallicity):
        """
        A helper to get a PHOENIX spectrum model filename
        from temperature, logg, and metallicity.

        Parameters
        ----------
        T : float
            Temperature (K)
        logg : float
            log10([surface gravity]/[cm/s**2])
        metallicity : float
            log10([metallicity]/[solar metallicity])

        Returns
        -------
        filename : string
            The filename of PHOENIX model (excluding directory).
        """

        f"lte{temperature:05.0f}-{logg:04.2f}{self._stringify_metallicity(metallicity)}.PHOENIX-ACES-AGSS-COND-2011-HiRes.fits"
        return f

    def _get_grid_filename(self, R, metallicity=0.0):
        """
        Get the filename of a pre-processed grid.

        Parameters
        ----------
        R : float
            The resolution of the grid.
        metallicity : float
            The stellar metallicity.

        Returns
        -------
        filename : str
            The filepath to the pre-processed grid.
        """
        if self._are_the_units_photons:
            unit_string = "photons"
        else:
            unit_string = "flux"

        filename = f"phoenix_{unit_string}_metallicity={metallicity:3.1f}_R={R:.0f}.npy"
        return os.path.join(self._directory_for_new_grids, filename)

    def _create_grids(self, metallicities=[0.0], remake=False, directory="."):
        """
        Create pre-processed grids for all resolutions.

        Parameters
        ----------
        metallicity : float
            The stellar metallicity.
        remake : bool
            Should we remake the library even if a file exists?
        directory : str
            Where should we create this library?
        """
        for metallicity in metallicities:
            for R in self._available_resolutions:
                self._create_grid(
                    R,
                    metallicity=metallicity,
                    remake=remake,
                    directory=directory,
                )

    def _upload_grids(self, destination):
        source = os.path.join(self._directory_for_new_grids, "phoenix_*.npy")
        command = f"rsync -v --progress {source} {destination}"
        return os.system(command)

    def _create_grid(self, R, metallicity=0.0, remake=False, directory="."):
        """
        Create a pre-processed grid for a single resolution.

        Parameters
        ----------
        R : float
            The resolution of the grid.
        metallicity : float
            The stellar metallicity.
        remake : bool
            Should we remake the library even if a file exists?
        directory : str
            Where should we create this library?
        """

        # figure out the directory where the models will be stored
        self._directory_for_new_grids = os.path.join(
            os.path.join(directory),
            "chromatic-model-stellar-spectra",
        )

        # make sure that directory exists
        try:
            os.mkdir(self._directory_for_new_grids)
        except FileExistsError:
            pass

        try:
            assert self._current_raw_metallicity == metallicity
        except (AttributeError, AssertionError):
            self._download_raw_data(metallicity=metallicity)

        # skip this resolution if already made
        filename = self._get_grid_filename(R, metallicity=metallicity)
        if os.path.exists(filename) and (not remake):
            print(
                textwrap.dedent(
                    f"""
                a grid for R={R}, metallicity={metallicity} exists at
                {self._get_grid_filename(R)}
                so we're not remaking it
                """
                )
            )
            return

        print(
            f"Creating a new grid for R={R}, metallicity={metallicity}. Its details are..."
        )
        shared = {}
        shared["grid"] = "PHOENIX-ACES-AGSS-COND-2011"
        shared["url"] = "https://phoenix.astro.physik.uni-goettingen.de/?page_id=15"
        shared["citation"] = "2013A&A…553A…6H"
        shared["photons"] = self._are_the_units_photons
        shared["R"] = R
        shared["metallicity"] = metallicity
        shared["filename"] = os.path.basename(filename)
        shared["chromatic-version"] = __version__
        unbinned_w = self._load_raw_wavelength()
        for k, v in shared.items():
            print(f"{k:>20} = {v}")

        d = {}
        for k, v in tqdm(list(self._raw_downloaded.items())):

            # load the unbinned spectrum
            unbinned_f = self._load_raw_spectrum(v)

            # convert from W to photon/s
            if self._are_the_units_photons:
                photon_energy = (con.h * con.c / unbinned_w) / u.photon
                unbinned_f = (unbinned_f / photon_energy).to("ph/(s m**2 nm)")
            else:
                unbinned_f = unbinned_f.to("W/(m**2 nm)")
            # figure out its stellar inputs
            T, logg, Z = self._get_Tgz_from_filename(k)
            if R == "original":
                w = unbinned_w
                f = unbinned_f
            else:
                binned = bintoR(unbinned_w, unbinned_f, R=R, drop_nans=False)
                w, f = binned["x"], binned["y"]

            if "wavelength" not in shared:
                shared["wavelength"] = w.value

            assert len(f) == len(shared["wavelength"])

            key = (T, logg, Z)
            d[key] = f.value

        # pull out the unique values of the keys
        for i, k in enumerate(self._keys_for_indexing):
            shared[k] = np.unique([x[i] for x in d])

        shared["wavelength_unit"] = w.unit.to_string()
        shared["spectrum_unit"] = f.unit.to_string()

        # save everything to an easy-to-load file
        np.save(filename, [shared, d], allow_pickle=True)
        print(f"That grid has been saved to {filename}.\n")

    def _find_smallest_R(self, R):
        """
        Make sure the smallest grid necessary to support
        a particular resolution is loaded into the library.

        Parameters
        ----------
        R : float
            The resolution of the grid.
        """

        i = np.flatnonzero(np.array(self._available_resolutions) >= R)[0]
        if i is not None:
            smallest_sufficient_R = self._available_resolutions[i]
        else:
            warnings.warn(
                f"""
            Your requested resolution of R={R}
            is higher than the largest possible value
            with uniform binning (R={np.max(self._available_resolutions)}).
            """
            )
            smallest_sufficient_R = np.max(self._available_resolutions)
        return smallest_sufficient_R

    def _load_grid(self, R, metallicity=0.0):
        """
        Load a pre-processed grid for a particular resolution.

        Parameters
        ----------
        R : float
            The resolution of the grid.
        metallicity : float
            The stellar metallicity.
        """
        self.metadata, self.models = np.load(
            self._get_grid_filename(R, metallicity=metallicity), allow_pickle=True
        )[()]

        self.units = {
            k: u.Unit(self.metadata[f"{k}_unit"]) for k in ["wavelength", "spectrum"]
        }
        self.wavelength = self.metadata["wavelength"] * self.units["wavelength"]

    def _find_bounds(self, value, key, inputs={}):
        """
        Find a mask where `possible` is immediately
        below or above `value`.

        Parameters
        ----------
        value : float
            The exact values to find.
        possible : array
            The possible grid point values to compare to.

        Returns
        -------
         :
        """
        possible = self.metadata[key]

        # return one index where it's exact
        if value in possible:
            return [value]

        # figure out above and below grid points otherwise
        try:
            above = np.min(possible[possible > value])
        except ValueError:
            above = None
        try:
            below = np.max(possible[possible <= value])
        except ValueError:
            below = None

        if (above is None) or (below is None):
            raise ValueError(
                f"""
            Your requested coordinate of
            {repr(inputs)}
            is outside the limits {np.min(possible)}<={key}<{np.max(possible)}.
            Please rewrite your code to avoid this happening
            or proceed very, very, very, very cautiously.
            """
            )
        else:
            return below, above

    def _get_interpolation_weights(self, value, bounds):
        """
        Get the interpolation weights for `value`
        relative to the `bounds` below and above.
        """

        # if there's only one value, the weight should be 1
        if np.size(bounds) == 1:
            return [1]
        elif np.size(bounds) == 2:
            span = bounds[1] - bounds[0]
            weight_below = (bounds[1] - value) / span
            weight_above = (value - bounds[0]) / span
            return weight_below, weight_above

    def get_spectrum(
        self, temperature=3000, logg=5.0, metallicity=0.0, visualize=False
    ):
        """
        Get a spectrum for an arbitrary temperature, logg, metallicity.
        """

        #
        inputs = dict(temperature=temperature, logg=logg, metallicity=metallicity)

        # figure out the
        bounding_temperature = self._find_bounds(
            temperature, key="temperature", inputs=inputs
        )
        bounding_logg = self._find_bounds(logg, key="logg", inputs=inputs)
        bounding_metallicity = self._find_bounds(
            metallicity, key="metallicity", inputs=inputs
        )

        if visualize:
            self.plot_available(**inputs)

        N = (
            np.size(bounding_temperature)
            * np.size(bounding_logg)
            * np.size(bounding_metallicity)
        )
        if N == 1:
            weights = [1]
            key = (bounding_temperature[0], bounding_logg[0], bounding_metallicity[0])
            spectrum = self.models[key].flatten()
        else:
            logT, bounding_logT = np.log(temperature), np.log(bounding_temperature)
            weight_temperature = self._get_interpolation_weights(logT, bounding_logT)
            weight_logg = self._get_interpolation_weights(logg, bounding_logg)
            weight_metallicity = self._get_interpolation_weights(
                metallicity, bounding_metallicity
            )

            weights = np.zeros(N)
            spectra = []
            i = 0
            for wt, t in zip(weight_temperature, bounding_temperature):
                for wg, g in zip(weight_logg, bounding_logg):
                    for wz, z in zip(weight_metallicity, bounding_metallicity):
                        weights[i] = wt * wg * wz
                        key = (t, g, z)
                        this_spectrum = self.models[key]
                        spectra.append(this_spectrum)
                        # print(f"{weights[i]} * [{key}]")
                        i += 1

            weight_sum = np.sum(weights)
            assert np.isclose(weight_sum, 1) or (weight_sum <= 1)
            weights /= weight_sum
            spectrum = np.sum(weights[:, np.newaxis] * spectra, axis=0)

        if visualize:
            fi = plt.figure(figsize=(8, 3))
            for w, s in zip(weights, spectra):
                plt.plot(self.wavelength, s, alpha=w)
            plt.plot(self.metadata["wavelength"], spectrum, color="black")
            plt.xlabel(
                f"Wavelength ({self.units['wavelength'].to_string('latex_inline')})"
            )
            plt.ylabel(
                f"Model Flux\n({self.units['spectrum'].to_string('latex_inline')})"
            )
            plt.suptitle(", ".join([f"{k}={v}" for k, v in inputs.items()]))

        return self.wavelength, spectrum * self.units["spectrum"]

    def plot_available(self, temperature=None, logg=None, metallicity=None):

        N = len(self._keys_for_indexing)
        fi, ax = plt.subplots(
            N, N, figsize=(8, 8), sharex="col", sharey="row", constrained_layout=True
        )
        labels = dict(
            temperature="Temperature (K)",
            logg="$log_{10}[g/(cm/s^2)]$",
            metallicity="[Z/H] (metallicity)",
        )
        gridkw = dict(marker=".", alpha=0.3)
        for i, ky in enumerate(self._keys_for_indexing):
            for j, kx in enumerate(self._keys_for_indexing):
                y = [k[i] for k in self.models]
                x = [k[j] for k in self.models]
                plt.sca(ax[i, j])
                plt.scatter(x, y, **gridkw)
                plt.scatter(locals()[kx], locals()[ky])
                # if j == 0:
                plt.ylabel(labels[ky])
                # if i == (N - 1):
                plt.xlabel(labels[kx])

    def plot_time_required(self, iterations=5):
        timings = {}
        for k in [
            "R",
            "load library",
            "get spectrum at grid point",
            "get interpolated spectrum",
        ]:
            timings[k] = []

        for R in tqdm(self._available_resolutions):
            for i in range(iterations):
                timings["R"].append(R)

                # how long does it take to load?
                start = get_current_seconds()
                self._load_grid(R)
                dt = get_current_seconds() - start
                timings["load library"].append(dt)

                # how long does it take to retrieve a spectrum that exists?
                start = get_current_seconds()
                self.get_spectrum(temperature=3000, logg=4.5, metallicity=0.0)
                dt = get_current_seconds() - start
                timings["get spectrum at grid point"].append(dt)

                # how long does it take to retrieve a spectrum that needs to be interpolated?
                start = get_current_seconds()
                self.get_spectrum(temperature=3456, logg=5.67, metallicity=0.0)
                dt = get_current_seconds() - start
                timings["get interpolated spectrum"].append(dt)

        t = Table(timings)
        plt.figure(figsize=(8, 4), dpi=300)
        for k in timings.keys():
            if k != "R":
                plt.loglog(timings["R"], timings[k], marker="o", label=k, alpha=0.3)
        plt.legend(bbox_to_anchor=(1, 1), frameon=False)
        plt.xlabel("R = $\lambda/\Delta\lambda$")
        plt.ylabel("Time Required")
        return t
