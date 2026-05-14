// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/**
 * @title SP500Market
 * @notice Marché de prédiction S&P 500 à 5 minutes sur Polygon.
 *         Chaque round: les utilisateurs misent UP ou DOWN en USDC.
 *         L'oracle poste le prix de clôture; les gagnants se partagent
 *         le pool des perdants moins les frais du protocole (3%).
 */
contract SP500Market is Ownable, ReentrancyGuard, Pausable {
    using SafeERC20 for IERC20;

    // ─────────────────────────────────────────────────────────────
    //  Types
    // ─────────────────────────────────────────────────────────────

    enum Position { UP, DOWN }

    struct BetInfo {
        Position position;
        uint256 amount;
        bool claimed;
    }

    struct Round {
        uint256 epoch;
        uint256 startTimestamp;
        uint256 lockTimestamp;   // oracle doit poster avant ici
        uint256 closeTimestamp;
        uint256 startPrice;      // SPX * 100  (ex: 520050 = 5200.50)
        uint256 closePrice;
        uint256 longAmount;      // total USDC misé UP
        uint256 shortAmount;     // total USDC misé DOWN
        uint256 rewardAmount;    // pool net après frais
        uint256 rewardBase;      // total misé par les gagnants
        bool    oracleCalled;
    }

    // ─────────────────────────────────────────────────────────────
    //  Constants
    // ─────────────────────────────────────────────────────────────

    uint256 public constant FEE_BPS   = 300;   // 3%
    uint256 public constant MIN_BET   = 1e6;   // 1 USDC (6 decimals)
    uint256 public constant INTERVAL  = 300;   // 5 minutes par round
    uint256 public constant LOCK_SECS = 30;    // fenêtre de lock avant clôture

    // ─────────────────────────────────────────────────────────────
    //  State
    // ─────────────────────────────────────────────────────────────

    IERC20  public immutable usdc;
    address public oracle;
    address public treasury;

    uint256 public currentEpoch;
    uint256 public treasuryAmount;

    mapping(uint256 => Round)                          public rounds;
    mapping(uint256 => mapping(address => BetInfo))    public ledger;
    mapping(address => uint256[])                      public userRounds;

    // ─────────────────────────────────────────────────────────────
    //  Events
    // ─────────────────────────────────────────────────────────────

    event RoundStarted(uint256 indexed epoch, uint256 startPrice, uint256 startTimestamp);
    event RoundSettled(uint256 indexed epoch, uint256 closePrice, uint256 longAmount, uint256 shortAmount);
    event BetUp   (address indexed user, uint256 indexed epoch, uint256 amount);
    event BetDown (address indexed user, uint256 indexed epoch, uint256 amount);
    event Claimed (address indexed user, uint256 indexed epoch, uint256 amount);

    // ─────────────────────────────────────────────────────────────
    //  Constructor
    // ─────────────────────────────────────────────────────────────

    constructor(address _usdc, address _oracle, address _treasury)
        Ownable(msg.sender)
    {
        usdc     = IERC20(_usdc);
        oracle   = _oracle;
        treasury = _treasury;
    }

    // ─────────────────────────────────────────────────────────────
    //  Modifiers
    // ─────────────────────────────────────────────────────────────

    modifier onlyOracle() {
        require(msg.sender == oracle, "Not oracle");
        _;
    }

    modifier bettable(uint256 epoch) {
        Round storage r = rounds[epoch];
        require(
            block.timestamp >= r.startTimestamp &&
            block.timestamp <  r.lockTimestamp,
            "Round not bettable"
        );
        _;
    }

    // ─────────────────────────────────────────────────────────────
    //  Oracle — gestion des rounds
    // ─────────────────────────────────────────────────────────────

    /**
     * @notice Démarre un nouveau round. Appelé par l'oracle toutes les 5 min.
     *         Si un round précédent n'a pas été settlé (tie ou absence de bets)
     *         il est annulé silencieusement.
     */
    function genesisStartRound(uint256 price) external onlyOracle whenNotPaused {
        require(currentEpoch == 0, "Already started");
        _startRound(price);
    }

    function executeRound(uint256 closePrice, uint256 newPrice)
        external
        onlyOracle
        whenNotPaused
    {
        require(currentEpoch > 0, "Not started");
        _settleRound(currentEpoch, closePrice);
        _startRound(newPrice);
    }

    function _startRound(uint256 price) internal {
        currentEpoch++;
        Round storage r = rounds[currentEpoch];
        r.epoch          = currentEpoch;
        r.startTimestamp = block.timestamp;
        r.lockTimestamp  = block.timestamp + INTERVAL - LOCK_SECS;
        r.closeTimestamp = block.timestamp + INTERVAL;
        r.startPrice     = price;
        emit RoundStarted(currentEpoch, price, block.timestamp);
    }

    function _settleRound(uint256 epoch, uint256 closePrice) internal {
        Round storage r = rounds[epoch];
        if (r.oracleCalled) return; // already settled

        r.closePrice   = closePrice;
        r.oracleCalled = true;

        uint256 total = r.longAmount + r.shortAmount;
        if (total == 0) return; // no bets — nothing to distribute

        uint256 fee = (total * FEE_BPS) / 10_000;
        treasuryAmount  += fee;
        r.rewardAmount   = total - fee;

        if (closePrice > r.startPrice) {
            r.rewardBase = r.longAmount;
        } else if (closePrice < r.startPrice) {
            r.rewardBase = r.shortAmount;
        } else {
            r.rewardBase = 0; // égalité → remboursement
        }

        emit RoundSettled(epoch, closePrice, r.longAmount, r.shortAmount);
    }

    // ─────────────────────────────────────────────────────────────
    //  Utilisateurs — mises
    // ─────────────────────────────────────────────────────────────

    function betUp(uint256 epoch, uint256 amount)
        external
        nonReentrant
        whenNotPaused
        bettable(epoch)
    {
        require(amount >= MIN_BET, "Below minimum");
        require(ledger[epoch][msg.sender].amount == 0, "Already bet");

        usdc.safeTransferFrom(msg.sender, address(this), amount);
        rounds[epoch].longAmount += amount;
        ledger[epoch][msg.sender] = BetInfo(Position.UP, amount, false);
        userRounds[msg.sender].push(epoch);

        emit BetUp(msg.sender, epoch, amount);
    }

    function betDown(uint256 epoch, uint256 amount)
        external
        nonReentrant
        whenNotPaused
        bettable(epoch)
    {
        require(amount >= MIN_BET, "Below minimum");
        require(ledger[epoch][msg.sender].amount == 0, "Already bet");

        usdc.safeTransferFrom(msg.sender, address(this), amount);
        rounds[epoch].shortAmount += amount;
        ledger[epoch][msg.sender] = BetInfo(Position.DOWN, amount, false);
        userRounds[msg.sender].push(epoch);

        emit BetDown(msg.sender, epoch, amount);
    }

    function claim(uint256[] calldata epochs) external nonReentrant {
        uint256 totalReward;
        for (uint256 i; i < epochs.length; i++) {
            uint256 epoch = epochs[i];
            Round storage r   = rounds[epoch];
            BetInfo storage b = ledger[epoch][msg.sender];

            require(r.oracleCalled, "Not settled");
            require(!b.claimed,     "Already claimed");
            b.claimed = true;

            uint256 payout;
            if (r.rewardBase == 0) {
                // Égalité: remboursement moins frais
                payout = b.amount - (b.amount * FEE_BPS) / 10_000;
            } else {
                bool isWinner =
                    (r.closePrice > r.startPrice && b.position == Position.UP) ||
                    (r.closePrice < r.startPrice && b.position == Position.DOWN);
                if (isWinner) {
                    payout = (b.amount * r.rewardAmount) / r.rewardBase;
                }
            }

            if (payout > 0) {
                totalReward += payout;
                emit Claimed(msg.sender, epoch, payout);
            }
        }
        if (totalReward > 0) usdc.safeTransfer(msg.sender, totalReward);
    }

    // ─────────────────────────────────────────────────────────────
    //  Views
    // ─────────────────────────────────────────────────────────────

    /**
     * @return upMult   multiplicateur UP  × 100 (ex: 197 = 1.97×)
     * @return downMult multiplicateur DOWN × 100
     */
    function getMultipliers(uint256 epoch)
        external view
        returns (uint256 upMult, uint256 downMult)
    {
        Round storage r = rounds[epoch];
        uint256 total = r.longAmount + r.shortAmount;
        if (total == 0) return (200, 200); // 2× par défaut si aucune mise

        uint256 net = (total * (10_000 - FEE_BPS)) / 10_000;
        upMult   = r.longAmount  > 0 ? (net * 100) / r.longAmount  : 10_000;
        downMult = r.shortAmount > 0 ? (net * 100) / r.shortAmount : 10_000;
    }

    function isClaimable(uint256 epoch, address user) external view returns (bool) {
        Round storage r   = rounds[epoch];
        BetInfo storage b = ledger[epoch][user];
        if (!r.oracleCalled || b.claimed || b.amount == 0) return false;
        if (r.rewardBase == 0) return true;
        return (r.closePrice > r.startPrice && b.position == Position.UP) ||
               (r.closePrice < r.startPrice && b.position == Position.DOWN);
    }

    function getUserRoundsPaginated(address user, uint256 cursor, uint256 size)
        external view
        returns (uint256[] memory epochList, BetInfo[] memory betList, uint256 next)
    {
        uint256 len = userRounds[user].length;
        uint256 count = (cursor + size > len) ? len - cursor : size;
        epochList = new uint256[](count);
        betList   = new BetInfo[](count);
        for (uint256 i; i < count; i++) {
            epochList[i] = userRounds[user][cursor + i];
            betList[i]   = ledger[epochList[i]][user];
        }
        return (epochList, betList, cursor + count);
    }

    // ─────────────────────────────────────────────────────────────
    //  Admin
    // ─────────────────────────────────────────────────────────────

    function setOracle(address _oracle)   external onlyOwner { oracle   = _oracle; }
    function setTreasury(address _treas)  external onlyOwner { treasury = _treas;  }
    function pause()   external onlyOwner { _pause();   }
    function unpause() external onlyOwner { _unpause(); }

    function withdrawTreasury() external onlyOwner {
        uint256 amt = treasuryAmount;
        treasuryAmount = 0;
        usdc.safeTransfer(treasury, amt);
    }
}
