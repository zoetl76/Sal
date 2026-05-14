require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config({ path: "../.env" });

const PRIVATE_KEY = process.env.DEPLOYER_PRIVATE_KEY || "0x" + "0".repeat(64);
const POLYGON_RPC = process.env.POLYGON_RPC_URL || "https://polygon-rpc.com";
const MUMBAI_RPC  = process.env.MUMBAI_RPC_URL  || "https://rpc-mumbai.maticvigil.com";
const POLYGONSCAN  = process.env.POLYGONSCAN_API_KEY || "";

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.20",
    settings: { optimizer: { enabled: true, runs: 200 } },
  },
  networks: {
    hardhat: {},
    mumbai: {
      url: MUMBAI_RPC,
      accounts: [PRIVATE_KEY],
      chainId: 80001,
    },
    polygon: {
      url: POLYGON_RPC,
      accounts: [PRIVATE_KEY],
      chainId: 137,
    },
  },
  etherscan: {
    apiKey: { polygon: POLYGONSCAN, polygonMumbai: POLYGONSCAN },
  },
};
